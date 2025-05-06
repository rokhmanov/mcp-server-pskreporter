# pskreporter_mcp_server.py
import asyncio
import json
import time
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

# DXCC Entity mapping from code to name
def load_dxcc_entities():
    global dxcc_entities
    
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
                print(f"Error processing line: {line} - {e}")

# Owner (hardcoded) information
OWNER_INFO = {
    "call": "W9KM",  # Replace with your callsign
    "locator": "EN51",  # Replace with your grid locator
    "country": "291"    # Entity code for USA
}

# Connect to MQTT server and handle callbacks
def setup_mqtt():
    global mqtt_client
    
    def on_connect(client, userdata, flags, rc, properties=None):
        print(f"Connected to PSKReporter MQTT with result code {rc}")
    
    def on_message(client, userdata, msg):
        try:
            data = json.loads(msg.payload)
            topic_parts = msg.topic.split('/')
            session_id = userdata.get('session_id')
            
            if session_id and session_id in active_sessions:
                spot = process_spot(data)
                if spot:
                    if 'spots' not in active_sessions[session_id]:
                        active_sessions[session_id]['spots'] = []
                    active_sessions[session_id]['spots'].append(spot)
                    # Limit stored spots to prevent memory issues
                    if len(active_sessions[session_id]['spots']) > 100:
                        active_sessions[session_id]['spots'] = active_sessions[session_id]['spots'][-100:]
        except Exception as e:
            print(f"Error processing message: {e}")
    
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    
    # Connect to PSKReporter MQTT server
    client.connect("mqtt.pskreporter.info", 1883, 60)
    client.loop_start()  # Start the MQTT loop in a background thread
    
    mqtt_client = client
    return client

# Process a spot from MQTT and format it nicely
def process_spot(raw_spot):
    try:
        spot = {
            'time': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(raw_spot.get('time', time.time()))),
            'callsign': raw_spot.get('sendercall', ''),
            'frequency': raw_spot.get('frequency', 0) / 1000000,  # Convert to MHz
            'mode': raw_spot.get('mode', ''),
            'locator': raw_spot.get('senderlocator', ''),
            'snr': raw_spot.get('snr', 0),
            'country': dxcc_entities.get(raw_spot.get('sendercountry', ''), 'Unknown')
        }
        
        # Add calculated fields
        # In a full implementation, add distance calculation based on locators
        
        return spot
    except Exception as e:
        print(f"Error processing spot: {e}")
        return None

# Create MQTT topic with proper filtering
def create_mqtt_topic(params):
    band = params.get('band', '+')
    mode = params.get('mode', '+')
    sendercountry = params.get('sendercountry', '+')
    senderlocator = params.get('senderlocator', '+')
    sendercall = params.get('sendercall', '+')
    
    # Apply owner filtering if needed
    if params.get('apply_owner_filter', False):
        # This would filter based on the hardcoded owner information
        pass
    
    return f"pskr/filter/v2/{band}/{mode}/{sendercountry}/{senderlocator}/{sendercall}"

# MCP handler for starting a subscription
@mcp.tool()
def start_subscription(band: Optional[str] = None, 
                       mode: Optional[str] = None,
                       sendercountry: Optional[str] = None, 
                       senderlocator: Optional[str] = None,
                       sendercall: Optional[str] = None,
                       apply_owner_filter: bool = False) -> Dict:
    params = {
        'band': band,
        'mode': mode,
        'sendercountry': sendercountry,
        'senderlocator': senderlocator,
        'sendercall': sendercall,
        'apply_owner_filter': apply_owner_filter
    }
    
    session_id = f"session_{int(time.time())}_{id(params)}"
    
    # Create topic for subscription
    topic = create_mqtt_topic(params)
    
    # Store session info
    active_sessions[session_id] = {
        'topic': topic,
        'params': params,
        'start_time': time.time(),
        'spots': []
    }
    
    # Subscribe to the topic
    mqtt_client.user_data_set({'session_id': session_id})
    mqtt_client.subscribe(topic)
    
    return {
        'status': 'success',
        'message': f'Started monitoring for spots matching your criteria',
        'session_id': session_id,
        'topic': topic
    }

# MCP handler for stopping a subscription
@mcp.tool()
def stop_subscription(session_id: str) -> Dict:
    if session_id in active_sessions:
        topic = active_sessions[session_id]['topic']
        mqtt_client.unsubscribe(topic)
        del active_sessions[session_id]
        return {
            'status': 'success',
            'message': f'Stopped monitoring session {session_id}'
        }
    else:
        return {
            'status': 'error',
            'message': f'Session {session_id} not found'
        }

# MCP handler for getting updates
@mcp.tool()
def get_updates(session_id: str) -> Dict:
    if session_id in active_sessions:
        # Get spots and clear the buffer
        spots = active_sessions[session_id].get('spots', [])
        active_sessions[session_id]['spots'] = []
        
        # Process the data for this specific query type
        params = active_sessions[session_id]['params']
        processed_response = process_query_response(spots, params)
        
        return {
            'status': 'success',
            'session_id': session_id,
            'updates': processed_response
        }
    else:
        return {
            'status': 'error',
            'message': f'Session {session_id} not found'
        }

# Process spots based on query type
def process_query_response(spots, params):
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
    
    return {
        'total_spots': len(spots),
        'unique_stations': len(stations),
        'stations': stations
    }

async def main():
    # Load DXCC entity mapping
    load_dxcc_entities()
    
    # Setup MQTT connection
    setup_mqtt()

if __name__ == "__main__":
    asyncio.run(main())
        
    # Start MCP server (non-async)
    import uvicorn
    uvicorn.run("pskreporter_mcp_server:mcp", host="0.0.0.0", port=8000)