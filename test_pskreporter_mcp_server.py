# test_pskreporter_mcp_server.py
import pytest
import json
from unittest.mock import patch, MagicMock

# Import the server module
from pskreporter_mcp_server import (
    load_dxcc_entities, 
    create_mqtt_topic, 
    process_spot,
    active_sessions,
    start_subscription,
    get_updates,
    stop_subscription
)

@pytest.fixture
def setup_test_data():
    # Create test data
    global dxcc_entities
    from pskreporter_mcp_server import dxcc_entities
    dxcc_entities = {
        "291": "United States of America",
        "339": "Japan"
    }
    return dxcc_entities

def test_load_dxcc_entities():
    with patch('builtins.open', new_callable=MagicMock) as mock_open:
        mock_open.return_value.__enter__.return_value.readlines.return_value = [
            '"291": "United States of America",',
            '"339": "Japan",'
        ]
        load_dxcc_entities()
        from pskreporter_mcp_server import dxcc_entities
        assert dxcc_entities["291"] == "United States of America"
        assert dxcc_entities["339"] == "Japan"

def test_create_mqtt_topic():
    # Test default topic with all wildcards
    assert create_mqtt_topic({}) == "pskr/filter/v2/+/+/+/+/+"
    
    # Test specific parameters
    params = {
        'band': '20m',
        'mode': 'FT8',
        'sendercountry': '339',
        'senderlocator': 'PM95',
        'sendercall': 'JA1ABC'
    }
    assert create_mqtt_topic(params) == "pskr/filter/v2/20m/FT8/339/PM95/JA1ABC"

def test_process_spot(setup_test_data):
    raw_spot = {
        'time': 1620000000,
        'sendercall': 'JA1ABC',
        'frequency': 14074000,  # Hz
        'mode': 'FT8',
        'senderlocator': 'PM95',
        'snr': -10,
        'sendercountry': '339'
    }
    
    processed = process_spot(raw_spot)
    assert processed['callsign'] == 'JA1ABC'
    assert processed['frequency'] == 14.074  # MHz
    assert processed['country'] == 'Japan'

@patch('pskreporter_mcp_server.mqtt_client')
def test_start_subscription(mock_mqtt):
    response = start_subscription(
        band='20m',
        mode='FT8',
        sendercountry=None, 
        senderlocator=None,
        sendercall=None
    )
    
    assert response['status'] == 'success'
    assert 'session_id' in response
    assert response['topic'].startswith('pskr/filter/v2/20m/FT8')
    
    # Check if session was stored
    session_id = response['session_id']
    assert session_id in active_sessions
    assert active_sessions[session_id]['topic'] == response['topic']

@patch('pskreporter_mcp_server.mqtt_client')
def test_stop_subscription(mock_mqtt):
    # First create a session
    response = start_subscription(band='20m')
    session_id = response['session_id']
    
    # Then stop it
    stop_response = stop_subscription(session_id)
    assert stop_response['status'] == 'success'
    assert session_id not in active_sessions

def test_get_updates_no_session():
    response = get_updates("nonexistent_session")
    assert response['status'] == 'error'
    assert 'not found' in response['message']

@patch('pskreporter_mcp_server.process_query_response')
def test_get_updates_with_session(mock_process):
    # Setup mock
    mock_process.return_value = {'total_spots': 0, 'unique_stations': 0, 'stations': {}}
    
    # Create session
    active_sessions['test_session'] = {
        'spots': [{'callsign': 'W1AW'}],
        'params': {}
    }
    
    # Get updates
    response = get_updates('test_session')
    assert response['status'] == 'success'
    assert 'updates' in response
    assert active_sessions['test_session']['spots'] == []  # Spots should be cleared