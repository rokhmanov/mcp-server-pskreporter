# pskreporter_mcp_server.py
import asyncio
import json
import time
import sys
import threading
from typing import Dict, List, Optional, Any

import paho.mqtt.client as mqtt
from mcp.server import FastMCP
from pydantic import BaseModel

# Initialize MCP server
mcp = FastMCP("pskreporter")
mqtt_client = None
dxcc_entities = {}  # entity_code -> entity_name
mqtt_connected = False

# Create a debug log file
debug_log = open("mcp_server_debug.log", "w")

# Debug print function that writes to file AND stderr
def debug_print(*args, **kwargs):
    """Print debug messages to both file and stderr"""
    timestamp = time.strftime("%H:%M:%S")
    message = " ".join(str(arg) for arg in args)
    log_line = f"[{timestamp}] {message}"
    
    # Write to file
    debug_log.write(log_line + "\n")
    debug_log.flush()
    
    # Also write to stderr (in case it's not suppressed)
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
                # Use more robust parsing for JSON-like format
                try:
                    # Split by first colon
                    parts = line.split(':', 1)
                    if len(parts) == 2:
                        # Clean up the parts
                        entity_code = parts[0].strip().strip('"')
                        # Remove quotes, commas and extra whitespace
                        entity_name = parts[1].strip().strip('"').strip(',').strip('"')
                        dxcc_entities[entity_code] = entity_name
                except Exception as e:
                    debug_print(f"Error processing line: {line} - {e}")
        debug_print(f"Loaded {len(dxcc_entities)} DXCC entities")
    except FileNotFoundError:
        debug_print("Warning: dxcc.txt not found, using empty entity list")
    except Exception as e:
        debug_print(f"Error loading DXCC entities: {e}")

# Connect to MQTT server and handle callbacks
def setup_mqtt():
    global mqtt_client, mqtt_connected
    
    debug_print("Setting up MQTT connection...")
    
    def on_connect(client, userdata, flags, rc, properties=None):
        global mqtt_connected
        debug_print(f"Connected to PSKReporter MQTT with result code {rc}")
        if rc != 0:
            debug_print(f"Failed to connect, return code {rc}")
            mqtt_connected = False
        else:
            mqtt_connected = True
            debug_print("MQTT connection established successfully!")
    
    def on_disconnect(client, userdata, flags, rc, properties=None):
        global mqtt_connected
        debug_print(f"Disconnected from MQTT broker with code: {rc}")
        mqtt_connected = False
    
    def on_log(client, userdata, level, buf):
        debug_print(f"MQTT LOG ({level}): {buf}")
    
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_log = on_log
        
        # Enable detailed logging for MQTT client
        client.enable_logger()
        
        debug_print("Attempting to connect to mqtt.pskreporter.info...")
        # Connect to PSKReporter MQTT server
        client.connect("mqtt.pskreporter.info", 1883, 60)
        
        # Start the loop in a separate thread to prevent blocking
        debug_print("Starting MQTT loop in background thread...")
        client.loop_start()
        
        # Wait for connection to establish
        debug_print("Waiting for MQTT connection to establish...")
        max_wait = 10
        waited = 0
        while not mqtt_connected and waited < max_wait:
            time.sleep(0.5)
            waited += 0.5
            debug_print(f"Waiting for connection... {waited}s")
        
        if mqtt_connected:
            debug_print("MQTT connection established successfully!")
        else:
            debug_print("Warning: MQTT connection not confirmed within timeout")
        
        mqtt_client = client
        return client
    except Exception as e:
        debug_print(f"Failed to connect to MQTT: {e}")
        import traceback
        debug_print("Exception traceback:")
        debug_print(traceback.format_exc())
        return None

# Process a spot from MQTT and format it with all available data
def process_spot(raw_spot):
    try:
        debug_print(f"Processing spot with keys: {list(raw_spot.keys())}")
        
        # Handle sender country lookup
        sender_country_code = raw_spot.get('sa', '')
        if sender_country_code:
            sender_country_key = f"{sender_country_code:03d}"
            sender_country_name = dxcc_entities.get(sender_country_key, 'Unknown')
        else:
            sender_country_name = 'Unknown'
        
        # Handle receiver country lookup
        receiver_country_code = raw_spot.get('ra', '')
        if receiver_country_code:
            receiver_country_key = f"{receiver_country_code:03d}"
            receiver_country_name = dxcc_entities.get(receiver_country_key, 'Unknown')
        else:
            receiver_country_name = 'Unknown'
        
        # Complete spot data with all PSKReporter fields
        spot = {
            'sequence': raw_spot.get('sq'),                                    # sequence number
            'frequency': raw_spot.get('f', 0) / 1000000,                      # MHz
            'mode': raw_spot.get('md', ''),                                   # mode
            'snr': raw_spot.get('rp', 0),                                     # SNR in dB
            'timestamp': raw_spot.get('t', time.time()),                      # Unix timestamp
            'time': time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime(raw_spot.get('t', time.time()))),  # Human readable UTC
            'sender_call': raw_spot.get('sc', ''),                           # sender callsign
            'sender_locator': raw_spot.get('sl', ''),                        # sender grid
            'receiver_call': raw_spot.get('rc', ''),                         # receiver callsign
            'receiver_locator': raw_spot.get('rl', ''),                      # receiver grid
            'sender_country_code': sender_country_code,                       # sender DXCC code
            'receiver_country_code': receiver_country_code,                   # receiver DXCC code
            'sender_country': sender_country_name,                           # sender country name
            'receiver_country': receiver_country_name,                       # receiver country name
            'band': raw_spot.get('b', '')                                    # band string
        }
        
        debug_print(f"Processed spot: {spot['sender_call']} -> {spot['receiver_call']} on {spot['frequency']:.6f} MHz")
        return spot
    except Exception as e:
        debug_print(f"Error processing spot: {e}")
        return None

# Create MQTT topic with proper filtering
def create_mqtt_topic(params):
    """
    Create PSK Reporter MQTT topic following their specification:
    pskr/filter/v2/{band}/{mode}/{sendercall}/{receivercall}/{senderlocator}/{receiverlocator}/{sendercountry}/{receivercountry}
    """
    debug_print(f"Creating MQTT topic with params: {params}")
    
    # Get parameters with proper case handling
    band = params.get('band')
    if band:
        band = band.lower()  # Band should be lowercase (e.g., 30m, 15m)
    else:
        band = '+'
    
    mode = params.get('mode')
    if mode:
        mode = mode.upper()  # Mode should be uppercase (e.g., FT8, FT4)
    else:
        mode = '+'
    
    # Sender parameters
    sendercall = params.get('sendercall') if params.get('sendercall') else '+'
    if sendercall != '+':
        sendercall = sendercall.upper()  # Callsigns should be uppercase
    
    senderlocator = params.get('senderlocator') if params.get('senderlocator') else '+'
    if senderlocator != '+':
        senderlocator = senderlocator.upper()  # Grid squares should be uppercase
        
    sendercountry = params.get('sendercountry') if params.get('sendercountry') else '+'
    
    # Receiver parameters
    receivercall = params.get('receivercall') if params.get('receivercall') else '+'
    if receivercall != '+':
        receivercall = receivercall.upper()  # Callsigns should be uppercase
        
    receiverlocator = params.get('receiverlocator') if params.get('receiverlocator') else '+'
    if receiverlocator != '+':
        receiverlocator = receiverlocator.upper()  # Grid squares should be uppercase
        
    receivercountry = params.get('receivercountry') if params.get('receivercountry') else '+'
    
    # Build the topic with all 8 parameters
    topic = f"pskr/filter/v2/{band}/{mode}/{sendercall}/{receivercall}/{senderlocator}/{receiverlocator}/{sendercountry}/{receivercountry}"
    
    # Add # at the end to match all subtopics (important for MQTT wildcards)
    topic += "/#"
    
    debug_print(f"Created topic: {topic}")
    return topic

# Simplified spot collection for the get_spots method
class SpotCollector:
    def __init__(self):
        self.spots = []
    
    def collect_spot(self, msg):
        try:
            data = json.loads(msg.payload)
            spot = process_spot(data)
            if spot:
                self.spots.append(spot)
                debug_print(f"Collected spot: {spot['sender_call']} on {spot['frequency']:.6f} MHz")
        except Exception as e:
            debug_print(f"Error collecting spot: {e}")

# Format response as clean Markdown for LLM consumption
def format_spots_as_markdown(spots, duration, total_spots, unique_stations):
    """Format the spots data as clean Markdown without debug information."""
    
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
    
    # Build markdown
    md = f"""# PSK Reporter Spots Collection

**Duration:** {duration} seconds  
**Total Spots:** {total_spots}  
**Unique Stations:** {unique_stations}

## Stations Heard

"""
    
    for sender_call, sender_spots in stations.items():
        # Get sender info from first spot
        first_spot = sender_spots[0]
        sender_country = first_spot['sender_country']
        sender_locator = first_spot['sender_locator']
        
        md += f"### {sender_call}"
        if sender_country != 'Unknown':
            md += f" ({sender_country})"
        if sender_locator:
            md += f" - Grid: {sender_locator}"
        md += "\n\n"
        
        for spot in sender_spots:
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
        
        md += "\n"
    
    return md

# Main MCP tool - simplified get_spots method
@mcp.tool()
def get_spots(band: Optional[str] = None, 
              mode: Optional[str] = None,
              sendercall: Optional[str] = None,
              receivercall: Optional[str] = None,
              senderlocator: Optional[str] = None,
              receiverlocator: Optional[str] = None,
              sendercountry: Optional[str] = None,
              receivercountry: Optional[str] = None,
              duration: int = 60) -> str:
    
    global mqtt_connected
    debug_print(f"\n*** GET_SPOTS CALLED ***")
    debug_print(f"Parameters: band={band}, mode={mode}, sendercountry={sendercountry}, senderlocator={senderlocator}, sendercall={sendercall}, duration={duration}")
    debug_print(f"MQTT connected: {mqtt_connected}")
    
    if not mqtt_client or not mqtt_connected:
        return "# Error\n\nMQTT client not connected. Please check server status."
    
    params = {
        'band': band,
        'mode': mode,
        'sendercall': sendercall,
        'receivercall': receivercall,
        'senderlocator': senderlocator,
        'receiverlocator': receiverlocator,
        'sendercountry': sendercountry,
        'receivercountry': receivercountry
    }
    
    # Create topic for subscription
    topic = create_mqtt_topic(params)
    debug_print(f"Subscribing to topic: {topic}")
    
    # Create spot collector
    collector = SpotCollector()
    
    # Set up message handler for this specific collection
    def on_message(client, userdata, msg):
        debug_print(f"Received message on topic: {msg.topic}")
        collector.collect_spot(msg)
    
    # Store the original message handler
    original_handler = mqtt_client.on_message
    
    try:
        # Set our custom message handler
        mqtt_client.on_message = on_message
        
        # Subscribe to the topic
        result = mqtt_client.subscribe(topic)
        debug_print(f"Subscribe result: {result}")
        
        if result[0] != 0:
            return f"# Error\n\nFailed to subscribe to MQTT topic: {topic}"
        
        # Wait for the specified duration to collect spots
        debug_print(f"Collecting spots for {duration} seconds...")
        time.sleep(duration)
        
        # Unsubscribe from the topic
        debug_print(f"Unsubscribing from topic: {topic}")
        mqtt_client.unsubscribe(topic)
        
        # Process the collected spots
        spots = collector.spots
        debug_print(f"Collected {len(spots)} spots")
        
        # Count unique stations (senders)
        unique_senders = set(spot['sender_call'] for spot in spots)
        unique_stations = len(unique_senders)
        
        # Format as clean Markdown for LLM
        markdown_response = format_spots_as_markdown(spots, duration, len(spots), unique_stations)
        
        debug_print(f"Returning markdown response with {len(spots)} spots from {unique_stations} stations")
        debug_print("*** GET_SPOTS COMPLETE ***\n")
        return markdown_response
        
    except Exception as e:
        debug_print(f"Error in get_spots: {e}")
        import traceback
        debug_print("Exception traceback:")
        debug_print(traceback.format_exc())
        return f"# Error\n\nInternal server error: {str(e)}"
    finally:
        # Restore the original message handler
        mqtt_client.on_message = original_handler

# Initialize everything when the module loads
debug_print("Starting PSK Reporter MCP Server...")
debug_print(f"Python version: {sys.version}")
debug_print(f"Current time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
load_dxcc_entities()
setup_mqtt()  # Setup MQTT in main thread

if __name__ == "__main__":
    debug_print("MCP server is running with stdio transport...")
    debug_print(f"MQTT connected: {mqtt_connected}")
    debug_print("Server startup complete, ready to receive MCP tool calls.")
    
    # Use the default stdio transport
    mcp.run()
