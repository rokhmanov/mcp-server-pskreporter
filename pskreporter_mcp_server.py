# Threaded version that doesn't block FastMCP
import json
import time
import sys
import threading
import os
import re
import yaml
from typing import Optional, Dict, List
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import paho.mqtt.client as mqtt
from mcp.server import FastMCP
from mcp.types import LATEST_PROTOCOL_VERSION, ToolAnnotations

# Initialize MCP server
mcp = FastMCP("PSKReporter DX Service", protocol_version=LATEST_PROTOCOL_VERSION)

# Load DXCC entities from YAML file
def load_dxcc_entities() -> Dict[str, Dict]:
    """Load DXCC entities from YAML file."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    yaml_path = os.path.join(script_dir, "dxcc_entities.yaml")
    
    try:
        with open(yaml_path, 'r', encoding='utf-8') as file:
            data = yaml.safe_load(file)
            return data.get('dxcc_entities', {})
    except FileNotFoundError:
        print(f"Warning: dxcc_entities.yaml not found at {yaml_path}")
        return {}
    except yaml.YAMLError as e:
        print(f"Error parsing dxcc_entities.yaml: {e}")
        return {}

# Load the DXCC entities
dxcc_entities_data = load_dxcc_entities()

# Create simple mapping for backward compatibility
dxcc_entities = {}
for code, entity_data in dxcc_entities_data.items():
    dxcc_entities[code] = entity_data['canonical_name']

# Create reverse mapping for country name lookup
country_name_to_code = {}
for code, entity_data in dxcc_entities_data.items():
    canonical_name = entity_data['canonical_name']
    name_variations = entity_data.get('name_variations', [])
    
    # Add canonical name (case insensitive)
    country_name_to_code[canonical_name.lower()] = code
    
    # Add variations (case insensitive)
    for variation in name_variations:
        country_name_to_code[variation.lower()] = code

# Function to convert country name to DXCC code
def country_name_to_dxcc_code(country_name):
    """Convert a country name to its DXCC code."""
    if not country_name:
        return None
    
    # Try exact match (case insensitive)
    country_lower = country_name.lower().strip()
    if country_lower in country_name_to_code:
        return country_name_to_code[country_lower]
    
    return None

# Function to get name variations for a country
def get_country_variations(country_name):
    """Get common variations for a country name."""
    # Find the entity by canonical name
    for code, entity_data in dxcc_entities_data.items():
        if entity_data['canonical_name'].lower() == country_name.lower():
            return entity_data.get('name_variations', [])
    
    return []

# Get the directory where this script is located
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))

# Create a debug log file
debug_log = open("mcp_server_debug.log", "w")

# Debug print function
def debug_print(*args, **kwargs):
    """Print debug messages to both file and stderr"""
    timestamp = time.strftime("%H:%M:%S")
    message = " ".join(str(arg) for arg in args)
    log_line = f"[{timestamp}] {message}"
    
    # Write to file
    debug_log.write(log_line + "\n")
    debug_log.flush()
    
    # Also write to stderr
    print(log_line, file=sys.stderr)
    sys.stderr.flush()

# Process a spot from MQTT and format it with all available data
def process_spot(raw_spot):
    try:
        sender_country_code = raw_spot.get('sa', '')
        if sender_country_code:
            sender_country_key = f"{sender_country_code:03d}"
            sender_country_name = dxcc_entities.get(sender_country_key, 'Unknown')
        else:
            sender_country_name = 'Unknown'
        
        receiver_country_code = raw_spot.get('ra', '')
        if receiver_country_code:
            receiver_country_key = f"{receiver_country_code:03d}"
            receiver_country_name = dxcc_entities.get(receiver_country_key, 'Unknown')
        else:
            receiver_country_name = 'Unknown'
        
        spot = {
            'sequence': raw_spot.get('sq'),
            'frequency': raw_spot.get('f', 0) / 1000000,
            'mode': raw_spot.get('md', ''),
            'snr': raw_spot.get('rp', 0),
            'timestamp': raw_spot.get('t', time.time()),
            'time': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(raw_spot.get('t', time.time()))),
            'sender_call': raw_spot.get('sc', ''),
            'sender_locator': raw_spot.get('sl', ''),
            'receiver_call': raw_spot.get('rc', ''),
            'receiver_locator': raw_spot.get('rl', ''),
            'sender_country_code': sender_country_code,
            'receiver_country_code': receiver_country_code,
            'sender_country': sender_country_name,
            'receiver_country': receiver_country_name,
            'band': raw_spot.get('b', '')
        }
        
        return spot
    except Exception as e:
        debug_print(f"Error processing spot: {e}")
        return None

# Create MQTT topic with proper filtering
def create_mqtt_topic(params):
    band = params.get('band')
    if band:
        band = band.lower()
    else:
        band = '+'
    
    mode = params.get('mode')
    if mode:
        mode = mode.upper()
    else:
        mode = '+'
    
    sendercall = params.get('sendercall') if params.get('sendercall') else '+'
    if sendercall != '+':
        sendercall = sendercall.upper()
    
    senderlocator = params.get('senderlocator') if params.get('senderlocator') else '+'
    if senderlocator != '+':
        senderlocator = senderlocator.upper()
        
    sendercountry = params.get('sendercountry') if params.get('sendercountry') else '+'
    
    receivercall = params.get('receivercall') if params.get('receivercall') else '+'
    if receivercall != '+':
        receivercall = receivercall.upper()
        
    receiverlocator = params.get('receiverlocator') if params.get('receiverlocator') else '+'
    if receiverlocator != '+':
        receiverlocator = receiverlocator.upper()
        
    receivercountry = params.get('receivercountry') if params.get('receivercountry') else '+'
    
    topic = f"pskr/filter/v2/{band}/{mode}/{sendercall}/{receivercall}/{senderlocator}/{receiverlocator}/{sendercountry}/{receivercountry}"
    topic += "/#"
    
    return topic

# Format response as clean Markdown for LLM consumption
def format_spots_as_markdown(spots, duration, total_spots, unique_stations, max_stations=50, max_spots_per_station=5):
    if total_spots == 0:
        return f"""# PSK Reporter Spots Collection

**Duration:** {duration} seconds  
**Result:** No spots collected during this period

*Try increasing the duration or using broader filters.*"""
    
    # Group spots by sender callsign
    stations = {}
    for spot in spots:
        sender_call = spot['sender_call']
        if sender_call not in stations:
            stations[sender_call] = []
        stations[sender_call].append(spot)
    
    # Sort stations by number of spots (most active first)
    sorted_stations = sorted(stations.items(), key=lambda x: len(x[1]), reverse=True)
    
    md = f"""# PSK Reporter Spots Collection

**Duration:** {duration} seconds  
**Total Spots:** {total_spots}  
**Unique Stations:** {unique_stations}

## Stations Heard

"""
    
    # Show stations (limited to prevent huge responses)
    display_stations = sorted_stations[:max_stations]
    
    for sender_call, sender_spots in display_stations:
        first_spot = sender_spots[0]
        sender_country = first_spot['sender_country']
        sender_locator = first_spot['sender_locator']
        spot_count = len(sender_spots)
        
        md += f"### {sender_call}"
        if sender_country != 'Unknown':
            md += f" ({sender_country})"
        if sender_locator:
            md += f" - Grid: {sender_locator}"
        if spot_count > max_spots_per_station:
            md += f" - {spot_count} spots total"
        md += "\n\n"
        
        # Show sample spots per station
        sample_spots = sender_spots[:max_spots_per_station]
        for spot in sample_spots:
            freq = spot['frequency']
            mode = spot['mode']
            snr = spot['snr']
            time_str = spot['time']
            receiver_call = spot['receiver_call']
            receiver_locator = spot['receiver_locator']
            receiver_country = spot['receiver_country']
            band = spot['band']
            
            md += f"- **{freq:.6f} MHz** ({band}) - {mode} - SNR: {snr:+d} dB - {time_str}\n"
            md += f"  - Received by: {receiver_call}"
            if receiver_locator:
                md += f" ({receiver_locator})"
            if receiver_country != 'Unknown':
                md += f" - {receiver_country}"
            md += "\n"
        
        if spot_count > max_spots_per_station:
            md += f"  - ... and {spot_count - max_spots_per_station} more spots\n"
        
        md += "\n"
    
    if len(sorted_stations) > max_stations:
        md += f"*Response limited to top {max_stations} stations to prevent oversized messages. {len(sorted_stations) - max_stations} additional stations were active.*\n"
    
    return md

# Simplified spot collection class
class SpotCollector:
    def __init__(self):
        self.spots = []
        self.lock = threading.Lock()
    
    def collect_spot(self, msg):
        try:
            data = json.loads(msg.payload)
            spot = process_spot(data)
            if spot:
                with self.lock:
                    self.spots.append(spot)
        except Exception as e:
            debug_print(f"Error collecting spot: {e}")

# Function to run MQTT collection in a separate thread
def collect_spots_threaded(params, duration):
    """Run MQTT spot collection in a separate thread"""
    debug_print("Starting threaded MQTT collection...")
    
    mqtt_client = None
    mqtt_connected = False
    collection_complete = False
    
    def on_connect(client, userdata, flags, rc, properties=None):
        nonlocal mqtt_connected
        if rc == 0:
            mqtt_connected = True
            debug_print("MQTT connected successfully in thread")
        else:
            debug_print(f"MQTT connection failed in thread with code: {rc}")
    
    try:
        mqtt_client = mqtt.Client()
        mqtt_client.on_connect = on_connect
        
        debug_print("Connecting to MQTT broker in thread...")
        mqtt_client.connect("mqtt.pskreporter.info", 1883, 60)
        mqtt_client.loop_start()
        
        # Wait for connection
        wait_time = 0
        while not mqtt_connected and wait_time < 10:
            time.sleep(0.1)
            wait_time += 0.1
        
        if not mqtt_connected:
            debug_print("Failed to connect to MQTT in thread")
            return [], "Failed to connect to MQTT broker"
        
        topic = create_mqtt_topic(params)
        collector = SpotCollector()
        
        def on_message(client, userdata, msg):
            collector.collect_spot(msg)
        
        mqtt_client.on_message = on_message
        
        debug_print(f"Subscribing to: {topic} in thread")
        result = mqtt_client.subscribe(topic)
        if result[0] != 0:
            debug_print("Failed to subscribe in thread")
            return [], "Failed to subscribe to MQTT topic"
        
        debug_print(f"Collecting spots for {duration} seconds in thread...")
        
        # Sleep in small increments to allow for interruption
        start_time = time.time()
        while time.time() - start_time < duration:
            time.sleep(0.1)
        
        debug_print("Collection complete in thread")
        mqtt_client.unsubscribe(topic)
        mqtt_client.loop_stop()
        mqtt_client.disconnect()
        
        spots = collector.spots
        debug_print(f"Thread collected {len(spots)} spots")
        
        return spots, None
        
    except Exception as e:
        debug_print(f"Error in threaded collection: {e}")
        return [], f"Error in collection: {str(e)}"
    finally:
        if mqtt_client:
            try:
                mqtt_client.loop_stop()
                mqtt_client.disconnect()
            except:
                pass

@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=False,
        idempotentHint=False,
        openWorldHint=True
    ),
    description="Collect real-time amateur radio propagation spots from PSKReporter MQTT feed. This tool connects to the PSKReporter service to retrieve live propagation data from amateur radio stations worldwide."
)
def get_spots(band: Optional[str] = None, 
              mode: Optional[str] = None,
              sendercall: Optional[str] = None,
              receivercall: Optional[str] = None,
              senderlocator: Optional[str] = None,
              receiverlocator: Optional[str] = None,
              sendercountry: Optional[str] = None,
              receivercountry: Optional[str] = None,
              duration: int = 10) -> str:
    """
    Collect real-time amateur radio propagation spots from PSKReporter.
    
    This tool connects to the PSKReporter MQTT service (mqtt.pskreporter.info) to retrieve
    live propagation data from amateur radio stations worldwide. The tool filters spots
    based on your parameters and returns formatted results showing station activity,
    frequencies, modes, signal strength, and locations.
    
    **Important Notes:**
    - **Collection Time**: This tool requires waiting time (default 10 seconds) to collect
      real-time data from the PSKReporter network
    - **Filtering Strategy**: Use specific parameters to narrow results. Fewer filters
      mean more spots returned, but the response is limited to prevent oversized messages
    - **Data Source**: Spots come from the global PSKReporter network of amateur radio
      stations reporting propagation conditions
    
    **Parameters:**
    - `band`: Amateur radio band (e.g., "20m", "40m", "80m", "160m", "10m", "15m", "17m", "30m", "12m", "6m", "2m")
    - `mode`: Operating mode (e.g., "FT8", "FT4", "CW", "SSB", "PSK31", "RTTY")
    - `sendercall`: Specific station callsign to filter for (e.g., "W9KM", "JA1ABC")
    - `receivercall`: Callsign of receiving station to filter for
    - `senderlocator`: Maidenhead grid locator of sending station (e.g., "EN51", "JO20")
    - `receiverlocator`: Maidenhead grid locator of receiving station
    - `sendercountry`: Country name for sender's country (e.g., "Japan", "USA", "Germany", "Swains Island")
    - `receivercountry`: Country name for receiver's country
    - `duration`: Collection time in seconds (default: 10, max: 10)
    
    **Country Name Examples:**
    The tool accepts country names with case-insensitive matching and partial search:
    - Full names: "United States of America", "Japan", "Germany"
    - Case variations: "japan", "JAPAN", "Japan" all work the same
    - Partial matches: "swains" will match "Swains I.", "korea" will match "Republic of Korea"
    - Common variations: "USA", "UK", "Germany" are automatically mapped to their full names
    
    **Country Name Discovery:**
    Use the `dxcc_entities` MCP resource to discover available countries and their variations:
    - Browse all 340 DXCC entities with their official names
    - See common variations for each country (e.g., "USA" for "United States of America")
    - Get usage examples and search tips
    
    **Common Use Cases:**
    1. **Find stations from a specific country**: Use `sendercountry` parameter
       - Example: "Give me 10 FT8 Japan stations on 20m" → `get_spots(mode="FT8", sendercountry="Japan", band="20m", duration=10)`
       - Example: "Show me USA stations on 40m" → `get_spots(sendercountry="USA", band="40m", duration=10)`
    
    2. **Check propagation to a specific location**: Use `receivercountry` and `receiverlocator`
       - Example: "What FT8 stations from Japan can I hear on 160m" → `get_spots(mode="FT8", sendercountry="Japan", band="160m", duration=10)`
    
    3. **Monitor a specific station**: Use `sendercall` parameter
       - Example: "On what bands and modes does W9KM operate" → `get_spots(sendercall="W9KM", duration=10)`
    
    4. **Check band activity**: Use `band` parameter
       - Example: "Show me 20m FT8 activity" → `get_spots(band="20m", mode="FT8", duration=10)`
    
    **Tips for Better Results:**
    - Use the full `duration` (10 seconds) for better spot collection
    - Combine multiple filters to get more specific results
    - Popular modes: FT8, FT4, CW, SSB
    - Popular bands: 20m, 40m, 80m, 160m, 10m
    - Use the `dxcc_entities` resource to find exact country names and variations
    
    **Response Format:**
    Returns a formatted markdown report showing:
    - Collection statistics (duration, total spots, unique stations)
    - Stations grouped by callsign with country and grid information
    - Sample spots showing frequency, mode, signal strength, and time
    - Receiver information for each spot
    
    **Data Source:** PSKReporter MQTT feed (mqtt.pskreporter.info)
    """
    
    debug_print(f"\n*** GET_SPOTS CALLED ***")
    debug_print(f"Parameters: band={band}, mode={mode}, sendercall={sendercall}, receivercall={receivercall}")
    debug_print(f"Parameters: senderlocator={senderlocator}, receiverlocator={receiverlocator}")
    debug_print(f"Parameters: sendercountry={sendercountry}, receivercountry={receivercountry}, duration={duration}")
    
    # Validate duration parameter
    if duration < 5:
        duration = 5
        debug_print(f"Duration adjusted to minimum 5 seconds")
    elif duration > 10:
        duration = 10
        debug_print(f"Duration capped at maximum 10 seconds")
    
    # Convert country names to DXCC codes if provided
    sendercountry_code = None
    receivercountry_code = None
    
    if sendercountry:
        sendercountry_code = country_name_to_dxcc_code(sendercountry)
        if sendercountry_code:
            debug_print(f"Converted sendercountry '{sendercountry}' to DXCC code '{sendercountry_code}'")
        else:
            debug_print(f"Warning: Could not convert sendercountry '{sendercountry}' to DXCC code")
    
    if receivercountry:
        receivercountry_code = country_name_to_dxcc_code(receivercountry)
        if receivercountry_code:
            debug_print(f"Converted receivercountry '{receivercountry}' to DXCC code '{receivercountry_code}'")
        else:
            debug_print(f"Warning: Could not convert receivercountry '{receivercountry}' to DXCC code")
    
    params = {
        'band': band, 'mode': mode, 'sendercall': sendercall,
        'receivercall': receivercall, 'senderlocator': senderlocator,
        'receiverlocator': receiverlocator, 'sendercountry': sendercountry_code,
        'receivercountry': receivercountry_code
    }
    
    try:
        debug_print("Starting MQTT collection in thread...")
        
        # Use ThreadPoolExecutor to run collection in background
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(collect_spots_threaded, params, duration)
            
            try:
                # Wait for completion with a reasonable timeout
                # Use a fixed timeout that's shorter than MCP client timeout
                max_timeout = min(duration + 5, 15)  # Cap at 15 seconds total
                spots, error = future.result(timeout=max_timeout)
                
                if error:
                    debug_print(f"Collection error: {error}")
                    return f"# Error\n\n{error}"
                
                unique_stations = len(set(spot['sender_call'] for spot in spots))
                debug_print(f"Collected {len(spots)} spots from {unique_stations} stations")
                
                markdown_response = format_spots_as_markdown(spots, duration, len(spots), unique_stations)
                debug_print(f"Markdown response created successfully, length: {len(markdown_response)} characters")
                debug_print("*** GET_SPOTS COMPLETE ***\n")
                
                return markdown_response
                
            except FutureTimeoutError:
                debug_print("MQTT collection timed out")
                return f"# Error\n\nCollection timed out after {max_timeout} seconds. Try reducing the duration or check your internet connection."
        
    except Exception as e:
        debug_print(f"Error in get_spots: {e}")
        import traceback
        debug_print(f"Exception traceback: {traceback.format_exc()}")
        return f"# Error\n\nInternal server error: {str(e)}"

@mcp.resource("mcp://pskreporter/dxcc_entities")
def get_dxcc_entities_resource():
    """Get the complete list of DXCC entities for country name lookup and discovery."""
    debug_print("*** DXCC_ENTITIES RESOURCE REQUESTED ***")
    
    # Create a sorted list for better presentation
    sorted_entities = sorted(dxcc_entities_data.items(), key=lambda x: int(x[0]))
    
    # Build markdown content
    markdown_content = """# DXCC Entities for Amateur Radio Country Filtering

This resource provides the complete list of DXCC (DX Century Club) entities for use with the `get_spots()` tool. Use these exact country names in the `sendercountry` or `receivercountry` parameters.

## Usage Tips

- **Case-insensitive**: All names work regardless of capitalization
- **Partial matching**: Use partial names (e.g., "swains" matches "Swains I.")
- **Common variations**: Many countries have automatic variations (e.g., "USA" → "United States of America")
- **Exact names**: Use the exact names from this list for best results

## Example Usage

```python
get_spots(sendercountry='Japan', mode='FT8', duration=10)
get_spots(sendercountry='United States of America', band='20m', duration=10)
get_spots(sendercountry='Swains I.', duration=10)
```

## Complete DXCC Entity List

| Code | Country Name | Common Variations |
|------|-------------|-------------------|
"""
    
    # Add each entity to the table
    for code, entity_data in sorted_entities:
        name = entity_data['canonical_name']
        variations = entity_data.get('name_variations', [])
        
        # Format variations as a comma-separated list
        variations_text = ", ".join(variations) if variations else "—"
        
        # Escape any pipe characters in the text to avoid breaking the markdown table
        name = name.replace("|", "\\|")
        variations_text = variations_text.replace("|", "\\|")
        
        markdown_content += f"| {code} | {name} | {variations_text} |\n"
    
    # Add footer information
    markdown_content += f"""
## Summary

- **Total Entities**: {len(dxcc_entities_data)}
- **Data Source**: DXCC (DX Century Club) official entity list
- **Last Updated**: Current as of latest DXCC standards

## Search Strategies

1. **Start with common names**: Try "USA", "UK", "Germany", "Japan"
2. **Use partial matches**: "swains" will find "Swains I."
3. **Check variations**: Look in the "Common Variations" column for alternatives
4. **Case doesn't matter**: "japan", "JAPAN", "Japan" all work the same

## Popular Countries

Some frequently used countries with their variations:

- **United States of America**: USA, US, America, United States
- **United Kingdom**: UK, Great Britain, Britain, England  
- **Germany**: Germany, Deutschland, DE
- **Japan**: Japan (no common variations)
- **Canada**: Canada (no common variations)
- **Australia**: Australia (no common variations)

---
*Data provided by PSK Reporter MCP Server - 73!*
"""
    
    debug_print(f"Returned DXCC entities resource with {len(dxcc_entities_data)} entities in markdown format")
    debug_print("*** DXCC_ENTITIES RESOURCE COMPLETE ***")
    
    return markdown_content

# Initialize everything when the module loads
debug_print("Starting PSK Reporter MCP Server...")
debug_print(f"Python version: {sys.version}")
debug_print(f"Loaded {len(dxcc_entities_data)} DXCC entities")

if __name__ == "__main__":
    debug_print("MCP server is running with stdio transport...")
    debug_print("Server startup complete, ready to receive MCP tool calls.")
    
    # Force flush stdout and stderr before starting MCP
    sys.stdout.flush()
    sys.stderr.flush()
    
    try:
        mcp.run()
    except Exception as e:
        debug_print(f"Error running MCP server: {e}")
        import traceback
        debug_print(f"Traceback: {traceback.format_exc()}")
    finally:
        if debug_log:
            debug_log.close()