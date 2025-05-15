# pskreporter_mcp_server_debug.py
import asyncio
import json
import time
import sys
import threading
from typing import Dict, List, Optional, Any

import paho.mqtt.client as mqtt
from mcp.server import FastMCP
import uvicorn
from pydantic import BaseModel

# Initialize MCP server
mcp = FastMCP("pskreporter")
mqtt_client = None
active_sessions = {}  # session_id -> subscription_info
dxcc_entities = {}  # entity_code -> entity_name
message_count = 0  # Debug counter
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

# Owner (hardcoded) information
OWNER_INFO = {
    "call": "W9KM",  # Replace with your callsign
    "locator": "EN51",  # Replace with your grid locator
    "country": "291"    # Entity code for USA
}

# Connect to MQTT server and handle callbacks
def setup_mqtt():
    global mqtt_client, message_count, mqtt_connected
    
    debug_print("Setting up MQTT connection...")
    
    def on_connect(client, userdata, flags, rc, properties=None):
        global mqtt_connected
        debug_print(f"Connected to PSKReporter MQTT with result code {rc}")
        debug_print(f"Connection flags: {flags}")
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
    
    def on_subscribe(client, userdata, mid, granted_qos, properties=None):
        debug_print(f"*** SUBSCRIPTION CONFIRMED *** Message ID: {mid}, Granted QoS: {granted_qos}")
    
    def on_unsubscribe(client, userdata, mid, properties=None):
        debug_print(f"Unsubscribed! Message ID: {mid}")
    
    def on_message(client, userdata, msg):
        global message_count
        message_count += 1
        
        debug_print(f"\n*** MESSAGE RECEIVED #{message_count} ***")
        debug_print(f"Topic: {msg.topic}")
        debug_print(f"QoS: {msg.qos}")
        debug_print(f"Payload length: {len(msg.payload)} bytes")
        debug_print(f"Timestamp: {time.time()}")
        
        try:
            # Try to decode as JSON
            data = json.loads(msg.payload)
            debug_print(f"JSON parsed successfully. Keys: {list(data.keys())}")
            
            # Print first 200 chars of payload for debugging
            payload_str = msg.payload.decode('utf-8')[:200]
            debug_print(f"Payload preview: {payload_str}...")
            
            topic = msg.topic
            
            # Find all sessions that should receive this message
            # by checking which topics match
            matching_sessions = []
            debug_print(f"Checking against {len(active_sessions)} active sessions...")
            for session_id, session_info in active_sessions.items():
                session_topic = session_info['topic']
                debug_print(f"Checking session {session_id} with topic {session_topic}")
                
                # Check if this message topic matches the session's subscription topic
                if topic_matches(topic, session_topic):
                    matching_sessions.append(session_id)
                    spot = process_spot(data)
                    if spot:
                        if 'spots' not in session_info:
                            session_info['spots'] = []
                        session_info['spots'].append(spot)
                        # Limit stored spots to prevent memory issues
                        if len(session_info['spots']) > 100:
                            session_info['spots'] = session_info['spots'][-100:]
                        debug_print(f"*** SPOT ADDED *** to session {session_id}: {spot['callsign']} on {spot['frequency']:.3f} MHz")
            
            debug_print(f"Message matched {len(matching_sessions)} sessions: {matching_sessions}")
            debug_print("*** MESSAGE PROCESSING COMPLETE ***\n")
            
        except json.JSONDecodeError as e:
            debug_print(f"JSON decode error: {e}")
            debug_print(f"Raw payload: {msg.payload}")
        except Exception as e:
            debug_print(f"Error processing message: {e}")
            import traceback
            debug_print("Exception traceback:")
            debug_print(traceback.format_exc())
    
    def on_log(client, userdata, level, buf):
        debug_print(f"MQTT LOG ({level}): {buf}")
    
    try:
        client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        client.on_connect = on_connect
        client.on_disconnect = on_disconnect
        client.on_subscribe = on_subscribe
        client.on_unsubscribe = on_unsubscribe
        client.on_message = on_message
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

def topic_matches(actual_topic, subscription_topic):
    """Check if an actual MQTT topic matches a subscription topic with wildcards."""
    debug_print(f"  Checking if '{actual_topic}' matches '{subscription_topic}'")
    
    # Handle the case where subscription has # at the end
    if subscription_topic.endswith('/#'):
        # Remove the /# from the end
        sub_base = subscription_topic[:-2]
        debug_print(f"  Subscription base: '{sub_base}'")
        
        # Split both topics into parts
        actual_parts = actual_topic.split('/')
        sub_parts = sub_base.split('/')
        
        debug_print(f"  Actual parts: {actual_parts}")
        debug_print(f"  Subscription parts: {sub_parts}")
        
        # Check if we have at least as many parts in actual as in subscription base
        if len(actual_parts) < len(sub_parts):
            debug_print(f"  Length mismatch: {len(actual_parts)} < {len(sub_parts)}")
            return False
        
        # Check each part up to the length of sub_parts
        for i in range(len(sub_parts)):
            if sub_parts[i] != '+' and sub_parts[i] != actual_parts[i]:
                debug_print(f"  Part {i} mismatch: '{actual_parts[i]}' vs '{sub_parts[i]}'")
                return False
        
        # If we get here, all parts match and # covers any remaining parts
        debug_print(f"  Topic matches! (with # wildcard covering {len(actual_parts) - len(sub_parts)} additional parts)")
        return True
    
    # Handle exact matching without #
    actual_parts = actual_topic.split('/')
    sub_parts = subscription_topic.split('/')
    
    if len(actual_parts) != len(sub_parts):
        debug_print(f"  Length mismatch: {len(actual_parts)} vs {len(sub_parts)}")
        return False
    
    for i, (actual, sub) in enumerate(zip(actual_parts, sub_parts)):
        if sub != '+' and sub != actual:
            debug_print(f"  Part {i} mismatch: '{actual}' vs '{sub}'")
            return False
    
    debug_print("  Topic matches!")
    return True

# Process a spot from MQTT and format it nicely
def process_spot(raw_spot):
    try:
        debug_print(f"Processing spot with keys: {list(raw_spot.keys())}")
        debug_print(f"Raw spot data: {raw_spot}")
        
        # PSK Reporter uses these field names:
        # sc = sender call
        # f = frequency (in Hz)
        # md = mode
        # sl = sender locator
        # rp = report (SNR)
        # sa = sender area/country
        # t = time (Unix timestamp)
        
        # Handle country code lookup with proper padding
        country_code = raw_spot.get('sa', '')
        if country_code:
            # Pad country code to 3 digits with leading zeros
            country_key = f"{country_code:03d}"
            country_name = dxcc_entities.get(country_key, 'Unknown')
            debug_print(f"Country lookup: {country_code} -> {country_key} -> {country_name}")
        else:
            country_name = 'Unknown'
        
        spot = {
            'time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(raw_spot.get('t', time.time()))),
            'callsign': raw_spot.get('sc', ''),  # Changed from 'sendercall' to 'sc'
            'frequency': raw_spot.get('f', 0) / 1000000,  # Changed from 'frequency' to 'f', convert Hz to MHz
            'mode': raw_spot.get('md', ''),  # Changed from 'mode' to 'md'
            'locator': raw_spot.get('sl', ''),  # Changed from 'senderlocator' to 'sl'
            'snr': raw_spot.get('rp', 0),  # Changed from 'snr' to 'rp'
            'country': country_name  # Use the processed country name
        }
        
        debug_print(f"Processed spot: {spot}")
        return spot
    except Exception as e:
        debug_print(f"Error processing spot: {e}")
        import traceback
        debug_print("Exception traceback:")
        debug_print(traceback.format_exc())
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
    
    # For now, we're focusing on sender filtering
    sendercall = params.get('sendercall') if params.get('sendercall') else '+'
    if sendercall != '+':
        sendercall = sendercall.upper()  # Callsigns should be uppercase
    
    # We'll use wildcards for receiver-related fields for now
    receivercall = '+'
    senderlocator = params.get('senderlocator') if params.get('senderlocator') else '+'
    if senderlocator != '+':
        senderlocator = senderlocator.upper()  # Grid squares should be uppercase
    receiverlocator = '+'
    sendercountry = params.get('sendercountry') if params.get('sendercountry') else '+'
    receivercountry = '+'
    
    # Apply owner filtering if needed
    if params.get('apply_owner_filter', False):
        # This would filter based on the hardcoded owner information
        pass
    
    # Build the topic with all 8 parameters
    topic = f"pskr/filter/v2/{band}/{mode}/{sendercall}/{receivercall}/{senderlocator}/{receiverlocator}/{sendercountry}/{receivercountry}"
    
    # Add # at the end to match all subtopics (important for MQTT wildcards)
    topic += "/#"
    
    debug_print(f"Created topic: {topic}")
    return topic

# MCP handler for starting a subscription
@mcp.tool()
def start_subscription(band: Optional[str] = None, 
                       mode: Optional[str] = None,
                       sendercountry: Optional[str] = None, 
                       senderlocator: Optional[str] = None,
                       sendercall: Optional[str] = None,
                       apply_owner_filter: bool = False) -> Dict:
    global mqtt_connected
    debug_print(f"\n*** START_SUBSCRIPTION CALLED ***")
    debug_print(f"Parameters: band={band}, mode={mode}, sendercountry={sendercountry}, senderlocator={senderlocator}, sendercall={sendercall}, apply_owner_filter={apply_owner_filter}")
    debug_print(f"MQTT connected: {mqtt_connected}")
    debug_print(f"Active sessions before: {list(active_sessions.keys())}")
    
    params = {
        'band': band,
        'mode': mode,
        'sendercountry': sendercountry,
        'senderlocator': senderlocator,
        'sendercall': sendercall,
        'apply_owner_filter': apply_owner_filter
    }
    
    session_id = f"session_{int(time.time())}_{id(params)}"
    debug_print(f"Generated session ID: {session_id}")
    
    # Create topic for subscription
    topic = create_mqtt_topic(params)
    
    # Store session info
    active_sessions[session_id] = {
        'topic': topic,
        'params': params,
        'start_time': time.time(),
        'spots': []
    }
    debug_print(f"Stored session info for {session_id}")
    debug_print(f"Active sessions now: {list(active_sessions.keys())}")
    
    # Subscribe to the topic
    if mqtt_client:
        debug_print(f"MQTT client status: Connected={mqtt_connected}")
        debug_print(f"About to subscribe to topic: {topic}")
        
        # Ensure we're connected before subscribing
        if not mqtt_connected:
            debug_print("Warning: MQTT not connected, subscribing anyway...")
        
        # Subscribe to the topic
        result = mqtt_client.subscribe(topic)
        debug_print(f"Subscribe result: {result}")
        debug_print(f"Result details: message_id={result[1] if result[0] == 0 else 'N/A'}")
        
        # Give the subscription time to take effect
        debug_print("Sleeping 2 seconds to allow subscription to propagate...")
        time.sleep(2)
        debug_print(f"Subscription should now be active for topic: {topic}")
    else:
        debug_print("ERROR: MQTT client not initialized!")
        return {
            'status': 'error',
            'message': 'MQTT client not initialized'
        }
    
    response = {
        'status': 'success',
        'message': f'Started monitoring for spots matching your criteria',
        'session_id': session_id,
        'topic': topic
    }
    debug_print(f"Returning response: {response}")
    debug_print("*** START_SUBSCRIPTION COMPLETE ***\n")
    return response

# MCP handler for stopping a subscription
@mcp.tool()
def stop_subscription(session_id: str) -> Dict:
    debug_print(f"\n*** STOP_SUBSCRIPTION CALLED ***")
    debug_print(f"Session ID: {session_id}")
    
    if session_id in active_sessions:
        topic = active_sessions[session_id]['topic']
        
        # Check if any other sessions are using the same topic
        same_topic_sessions = [s for s in active_sessions.values() if s['topic'] == topic]
        
        # Only unsubscribe if this is the last session using this topic
        if len(same_topic_sessions) <= 1:
            debug_print(f"Unsubscribing from topic: {topic}")
            if mqtt_client:
                result = mqtt_client.unsubscribe(topic)
                debug_print(f"Unsubscribe result: {result}")
        
        del active_sessions[session_id]
        debug_print(f"Removed session {session_id}")
        debug_print(f"Active sessions now: {list(active_sessions.keys())}")
        return {
            'status': 'success',
            'message': f'Stopped monitoring session {session_id}'
        }
    else:
        debug_print(f"Session {session_id} not found in active_sessions")
        return {
            'status': 'error',
            'message': f'Session {session_id} not found'
        }

# MCP handler for getting updates
@mcp.tool()
def get_updates(session_id: str) -> Dict:
    global message_count
    debug_print(f"\n*** GET_UPDATES CALLED ***")
    debug_print(f"Session: {session_id}")
    debug_print(f"Total MQTT messages received so far: {message_count}")
    debug_print(f"Active sessions: {list(active_sessions.keys())}")
    debug_print(f"MQTT connected: {mqtt_connected}")
    
    try:
        if session_id in active_sessions:
            # Get spots and clear the buffer
            spots = active_sessions[session_id].get('spots', [])
            spot_count_before = len(spots)
            active_sessions[session_id]['spots'] = []
            
            debug_print(f"Found {spot_count_before} spots for session {session_id}")
            debug_print(f"Session topic: {active_sessions[session_id]['topic']}")
            debug_print(f"Session params: {active_sessions[session_id]['params']}")
            
            # Limit the number of spots to prevent large responses
            MAX_SPOTS_PER_UPDATE = 50
            if len(spots) > MAX_SPOTS_PER_UPDATE:
                debug_print(f"Limiting spots from {len(spots)} to {MAX_SPOTS_PER_UPDATE}")
                spots = spots[-MAX_SPOTS_PER_UPDATE:]  # Keep the most recent spots
            
            # Process the data for this specific query type
            params = active_sessions[session_id]['params']
            processed_response = process_query_response(spots, params)
            
            response = {
                'status': 'success',
                'session_id': session_id,
                'updates': processed_response
            }
            
            # Log response size for debugging
            response_json = json.dumps(response)
            debug_print(f"Response size: {len(response_json)} characters")
            debug_print(f"Returning get_updates response with {processed_response.get('total_spots', 0)} spots")
            debug_print("*** GET_UPDATES COMPLETE ***\n")
            return response
        else:
            debug_print(f"Session {session_id} not found in active_sessions")
            debug_print(f"Available sessions: {list(active_sessions.keys())}")
            return {
                'status': 'error',
                'message': f'Session {session_id} not found'
            }
    except Exception as e:
        debug_print(f"ERROR in get_updates: {e}")
        import traceback
        debug_print("Exception traceback:")
        debug_print(traceback.format_exc())
        return {
            'status': 'error',
            'message': f'Internal error: {str(e)}'
        }

# Process spots based on query type
def process_query_response(spots, params):
    debug_print(f"Processing {len(spots)} spots with params: {params}")
    
    # This would be expanded based on different query types
    # For example, "best DX" would sort by distance
    # "Contact Japan stations" would filter by country
    
    # Group spots by callsign and band to show stations on multiple bands
    stations = {}
    for spot in spots:
        callsign = spot['callsign']
        if callsign not in stations:
            stations[callsign] = []
        
        # Check if we already have this band/mode combination
        band_mode = (spot['frequency'], spot['mode'])
        existing = False
        for s in stations[callsign]:
            if (s['frequency'], s['mode']) == band_mode:
                existing = True
                break
                
        if not existing:
            stations[callsign].append(spot)
    
    result = {
        'total_spots': len(spots),
        'unique_stations': len(stations),
        'stations': stations
    }
    debug_print(f"Processed response: {result}")
    return result


# Add this function to the server file
def cleanup_old_sessions():
    """Clean up sessions that are older than 1 hour"""
    current_time = time.time()
    sessions_to_remove = []
    
    for session_id, session_info in active_sessions.items():
        session_age = current_time - session_info['start_time']
        if session_age > 3600:  # 1 hour
            debug_print(f"Marking old session {session_id} for cleanup (age: {session_age:.1f}s)")
            sessions_to_remove.append(session_id)
    
    for session_id in sessions_to_remove:
        debug_print(f"Cleaning up old session: {session_id}")
        if mqtt_client:
            topic = active_sessions[session_id]['topic']
            mqtt_client.unsubscribe(topic)
        del active_sessions[session_id]


# Initialize everything when the module loads
debug_print("Starting PSK Reporter MCP Server...")
debug_print(f"Python version: {sys.version}")
debug_print(f"Current time: {time.strftime('%Y-%m-%d %H:%M:%S')}")
load_dxcc_entities()

# Setup MQTT in a way that doesn't block the main thread
debug_print("Initializing MQTT connection...")
mqtt_thread = threading.Thread(target=setup_mqtt, daemon=True)
mqtt_thread.start()

# Give the MQTT thread time to start
time.sleep(3)

if __name__ == "__main__":
    debug_print("MCP server is running with stdio transport...")
    debug_print("To use HTTP transport, change the implementation.")
    debug_print(f"MQTT connected: {mqtt_connected}")
    debug_print("Server startup complete, ready to receive MCP tool calls.")
    

    def periodic_cleanup():
        while True:
            time.sleep(300)  # Every 5 minutes
            cleanup_old_sessions()

    cleanup_thread = threading.Thread(target=periodic_cleanup, daemon=True)
    cleanup_thread.start()

    # Use the default stdio transport
    # The client will need to connect via stdio, not HTTP
    mcp.run()