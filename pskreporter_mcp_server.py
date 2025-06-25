# Threaded version that doesn't block FastMCP
import json
import time
import sys
import threading
from typing import Optional
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError

import paho.mqtt.client as mqtt
from mcp.server import FastMCP
from mcp.types import LATEST_PROTOCOL_VERSION, ToolAnnotations

# Initialize MCP server
mcp = FastMCP("PSKReporter DX Service", protocol_version=LATEST_PROTOCOL_VERSION)
dxcc_entities = {}  # entity_code -> entity_name

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

# DXCC Entity mapping from code to name
def load_dxcc_entities():
    global dxcc_entities
    
    debug_print("Loading DXCC entities...")
    try:
        with open("dxcc.txt", "r") as f:
            lines = f.readlines()
        
        dxcc_entities = {}
        for line in lines:
            line = line.strip()
            if line and not line.startswith("#"):
                try:
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        entity_code = parts[0].strip().strip('"')
                        entity_name = parts[1].strip().strip('"').strip(',').strip('"')
                        dxcc_entities[entity_code] = entity_name
                except Exception as e:
                    debug_print(f"Error processing line: {line} - {e}")
        debug_print(f"Loaded {len(dxcc_entities)} DXCC entities")
    except FileNotFoundError:
        debug_print("Warning: dxcc.txt not found, using empty entity list")
    except Exception as e:
        debug_print(f"Error loading DXCC entities: {e}")

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
    - `sendercountry`: DXCC entity code for sender's country (use search_dxcc_entities() to find codes)
    - `receivercountry`: DXCC entity code for receiver's country
    - `duration`: Collection time in seconds (default: 10, max: 10)
    
    **Common Use Cases:**
    1. **Find stations from a specific country**: Use `sendercountry` parameter
       - Example: "Give me 10 FT8 Japan stations on 20m" → `get_spots(mode="FT8", sendercountry="339", band="20m", duration=10)`
    
    2. **Check propagation to a specific location**: Use `receivercountry` and `receiverlocator`
       - Example: "What FT8 stations from Japan can I hear on 160m" → `get_spots(mode="FT8", sendercountry="339", band="160m", duration=10)`
    
    3. **Monitor a specific station**: Use `sendercall` parameter
       - Example: "On what bands and modes does W9KM operate" → `get_spots(sendercall="W9KM", duration=10)`
    
    4. **Check band activity**: Use `band` parameter
       - Example: "Show me 20m FT8 activity" → `get_spots(band="20m", mode="FT8", duration=10)`
    
    **Tips for Better Results:**
    - Use the full `duration` (10 seconds) for better spot collection
    - Combine multiple filters to get more specific results
    - Use `search_dxcc_entities()` to find country codes
    - Popular modes: FT8, FT4, CW, SSB
    - Popular bands: 20m, 40m, 80m, 160m, 10m
    
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
    
    params = {
        'band': band, 'mode': mode, 'sendercall': sendercall,
        'receivercall': receivercall, 'senderlocator': senderlocator,
        'receiverlocator': receiverlocator, 'sendercountry': sendercountry,
        'receivercountry': receivercountry
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

@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        idempotentHint=True,
        openWorldHint=False
    ),
    description="Get the list of DXCC entities (country codes and names) for mapping country names to entity codes."
)
def get_dxcc_entities() -> str:
    """
    Returns the complete list of DXCC entities as a formatted table.
    This is useful for converting country names to entity codes when filtering spots.
    """
    debug_print("*** GET_DXCC_ENTITIES CALLED ***")
    
    if not dxcc_entities:
        debug_print("DXCC entities not loaded, attempting to load...")
        load_dxcc_entities()
    
    if not dxcc_entities:
        return "# Error\n\nDXCC entities could not be loaded. Please check if dxcc.txt is available."
    
    # Create a sorted list for better presentation
    sorted_entities = sorted(dxcc_entities.items(), key=lambda x: int(x[0]))
    
    md = f"""# DXCC Entities Reference

**Total Entities:** {len(dxcc_entities)}

This resource provides the mapping between DXCC entity codes and country/territory names used by PSKReporter.

## Entity Code to Country Name Mapping

| Code | Country/Territory |
|------|------------------|"""
    
    for entity_code, entity_name in sorted_entities:
        md += f"\n| {entity_code} | {entity_name} |"
    
    md += f"""

## Usage Examples

- To filter for stations from Japan, use `sendercountry=339` or `receivercountry=339`
- To filter for stations from the United States, use `sendercountry=291` or `receivercountry=291`
- To filter for stations from Germany, use `sendercountry=230` or `receivercountry=230`

## Search Tips

You can search this list to find the correct entity code for any country or territory. Common examples:
- **Japan**: 339
- **United States**: 291  
- **Germany**: 230
- **United Kingdom**: 223 (England), 265 (Northern Ireland), 279 (Scotland), 294 (Wales)
- **Canada**: 1
- **Australia**: 150

*Note: Some countries have multiple entity codes for different territories or regions.*"""
    
    debug_print(f"Returned {len(dxcc_entities)} DXCC entities")
    debug_print("*** GET_DXCC_ENTITIES COMPLETE ***")
    
    return md

@mcp.tool(
    annotations=ToolAnnotations(
        readOnlyHint=True,
        idempotentHint=True,
        openWorldHint=False
    ),
    description="Search for DXCC entities by country name or partial match."
)
def search_dxcc_entities(query: str) -> str:
    """
    Search for DXCC entities by country name or partial match.
    Useful for finding entity codes when you know part of a country name.
    """
    debug_print(f"*** SEARCH_DXCC_ENTITIES CALLED ***")
    debug_print(f"Query: {query}")
    
    if not dxcc_entities:
        debug_print("DXCC entities not loaded, attempting to load...")
        load_dxcc_entities()
    
    if not dxcc_entities:
        return "# Error\n\nDXCC entities could not be loaded. Please check if dxcc.txt is available."
    
    query_lower = query.lower()
    matches = []
    
    for entity_code, entity_name in dxcc_entities.items():
        if query_lower in entity_name.lower():
            matches.append((entity_code, entity_name))
    
    # Sort matches by entity code
    matches.sort(key=lambda x: int(x[0]))
    
    if not matches:
        return f"""# DXCC Entity Search Results

**Query:** "{query}"

No DXCC entities found matching your search.

Try searching for:
- Partial country names (e.g., "japan" for "Japan")
- Common abbreviations (e.g., "usa" for "United States of America")
- Territory names (e.g., "hawaii" for "Hawaii")"""
    
    md = f"""# DXCC Entity Search Results

**Query:** "{query}"  
**Found:** {len(matches)} matching entities

## Matching Entities

| Code | Country/Territory |
|------|------------------|"""
    
    for entity_code, entity_name in matches:
        md += f"\n| {entity_code} | {entity_name} |"
    
    if len(matches) == 1:
        entity_code, entity_name = matches[0]
        md += f"""

## Usage Example

To filter for stations from {entity_name}, use:
- `sendercountry={entity_code}` for sender country filter
- `receivercountry={entity_code}` for receiver country filter

Example: `get_spots(sendercountry="{entity_code}", duration=10)`"""
    
    debug_print(f"Found {len(matches)} matches for query '{query}'")
    debug_print("*** SEARCH_DXCC_ENTITIES COMPLETE ***")
    
    return md

# Initialize everything when the module loads
debug_print("Starting PSK Reporter MCP Server...")
debug_print(f"Python version: {sys.version}")
load_dxcc_entities()

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