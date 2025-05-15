#!/usr/bin/env python
# pskreporter_mcp_stdio_client.py
"""
PSK Reporter MCP Client for stdio transport - Fixed version with proper MCP response parsing

This client works with the default MCP stdio transport
"""

import asyncio
import json
import subprocess
import sys
import argparse
import time
from typing import Dict, Any, Optional

class PSKReporterSTDIOClient:
    def __init__(self, server_path: str = "pskreporter_mcp_server_debug.py"):  # Updated default
        self.server_path = server_path
        self.process = None
        self.request_id = 0
    
    async def start_server(self):
        """Start the MCP server as a subprocess."""
        print(f"Starting server: {self.server_path}")
        
        # Check if the server file exists
        import os
        if not os.path.exists(self.server_path):
            print(f"ERROR: Server file not found: {self.server_path}")
            raise Exception(f"Server file not found: {self.server_path}")
        
        self.process = await asyncio.create_subprocess_exec(
            sys.executable, self.server_path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE
        )
        print("MCP server process started")
        
        # Give the server a moment to initialize
        await asyncio.sleep(2)
        
        # Check if process is still running
        if self.process.returncode is not None:
            print(f"ERROR: Server process exited with code: {self.process.returncode}")
            # Try to read stderr
            stderr_data = await self.process.stderr.read()
            if stderr_data:
                print(f"Server stderr: {stderr_data.decode()}")
            raise Exception(f"Server process failed to start")
        
        # Initialize the MCP connection
        await self.initialize()
    
    async def initialize(self):
        """Initialize the MCP connection with proper handshake."""
        print("Initializing MCP connection...")
        init_request = {
            "jsonrpc": "2.0",
            "id": self.next_id(),
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {
                    "tools": {}
                },
                "clientInfo": {
                    "name": "pskreporter-client",
                    "version": "1.0.0"
                }
            }
        }
        
        print("Sending initialize request...")
        response = await self.send_request_raw(init_request)
        print(f"Initialize response: {response}")
        
        if response.get("error"):
            raise Exception(f"Failed to initialize: {response['error']}")
        
        # Send initialized notification
        print("Sending initialized notification...")
        initialized_notification = {
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        }
        await self.send_notification(initialized_notification)
        print("MCP initialization complete")
    
    def next_id(self) -> int:
        """Get the next request ID."""
        self.request_id += 1
        return self.request_id
    
    async def send_notification(self, notification: Dict[str, Any]):
        """Send a notification (no response expected)."""
        notification_json = json.dumps(notification) + "\n"
        self.process.stdin.write(notification_json.encode())
        await self.process.stdin.drain()
    
    async def send_request_raw(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Send a raw JSON-RPC request and get the response."""
        # Send request
        request_json = json.dumps(request) + "\n"
        print(f"Sending request: {json.dumps(request, indent=2)}")
        self.process.stdin.write(request_json.encode())
        await self.process.stdin.drain()
        
        # Read response with better error handling
        try:
            print("Waiting for response...")
            # Add timeout for readline
            response_line = await asyncio.wait_for(self.process.stdout.readline(), timeout=10.0)
            
            if not response_line:
                # Check if process ended
                if self.process.returncode is not None:
                    raise Exception(f"Server process ended with code: {self.process.returncode}")
                raise Exception("No response from server")
            
            response_text = response_line.decode().strip()
            if not response_text:
                raise Exception("Empty response from server")
            
            print(f"Received response: {response_text}")
            response = json.loads(response_text)
            return response
        except asyncio.TimeoutError:
            print("Timeout waiting for server response")
            # Check if the process is still alive
            if self.process.returncode is not None:
                print(f"Server process has exited with code: {self.process.returncode}")
            raise Exception("Timeout waiting for server response")
        except json.JSONDecodeError as e:
            print(f"Failed to parse JSON response: {e}")
            print(f"Raw response: {response_line}")
            raise
    
    def parse_mcp_response(self, mcp_result: Dict[str, Any]) -> Dict[str, Any]:
        """Parse MCP response format to extract the actual content."""
        if "isError" in mcp_result and mcp_result["isError"]:
            return {"status": "error", "message": "MCP error in response"}
        
        if "content" in mcp_result and mcp_result["content"]:
            # Get the first content item
            content_item = mcp_result["content"][0]
            if content_item.get("type") == "text":
                # Parse the JSON string in the text field
                try:
                    text_content = content_item["text"]
                    return json.loads(text_content)
                except json.JSONDecodeError:
                    return {"status": "error", "message": f"Invalid JSON in response: {text_content}"}
        
        return {"status": "error", "message": "Unexpected response format"}
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool using the proper MCP format."""
        request = {
            "jsonrpc": "2.0",
            "id": self.next_id(),
            "method": "tools/call",
            "params": {
                "name": tool_name,
                "arguments": arguments
            }
        }
        
        try:
            response = await self.send_request_raw(request)
            
            if "error" in response:
                return {"status": "error", "message": response["error"]}
            
            # Parse the MCP response format
            result = response.get("result", {})
            return self.parse_mcp_response(result)
        except Exception as e:
            return {"status": "error", "message": f"Communication error: {e}"}
    
    async def stop_server(self):
        """Stop the MCP server."""
        if self.process:
            # Check server stderr for errors
            try:
                # Try to read any errors from stderr with timeout
                stderr_data = await asyncio.wait_for(self.process.stderr.read(1024), timeout=0.1)
                if stderr_data:
                    print(f"Server stderr: {stderr_data.decode()}")
            except (asyncio.TimeoutError, Exception):
                pass
            
            self.process.terminate()
            await self.process.wait()
            print("MCP server stopped")
    
    async def start_subscription(self, **kwargs):
        """Start a subscription."""
        params = {k: v for k, v in kwargs.items() if v is not None}
        result = await self.call_tool("start_subscription", params)
        return result
    
    async def get_updates(self, session_id: str):
        """Get updates for a session."""
        result = await self.call_tool("get_updates", {"session_id": session_id})
        return result
    
    async def stop_subscription(self, session_id: str):
        """Stop a subscription."""
        result = await self.call_tool("stop_subscription", {"session_id": session_id})
        return result


def load_last_session() -> Optional[str]:
    """Load the last session ID from file if it exists."""
    try:
        with open("last_session.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


def save_session_id(session_id: str):
    """Save session ID to file."""
    with open("last_session.txt", "w") as f:
        f.write(session_id)


async def start_subscription(args):
    """Start a subscription with the specified filters."""
    client = PSKReporterSTDIOClient()
    
    try:
        await client.start_server()
        
        result = await client.start_subscription(
            band=args.band,
            mode=args.mode,
            sendercountry=args.country,
            senderlocator=args.locator,
            sendercall=args.callsign,
            apply_owner_filter=args.owner_filter
        )
        
        print("Response:", json.dumps(result, indent=2))
        
        if result.get("status") == "success":
            session_id = result.get("session_id")
            save_session_id(session_id)
            print(f"\nSession ID saved: {session_id}")
            print(f"Topic: {result.get('topic')}")
            
            # If continuous mode requested, start monitoring
            if args.continuous:
                print("\nStarting continuous update mode. Press Ctrl+C to exit.")
                print("Waiting 10 seconds for subscription to take effect...")
                await asyncio.sleep(10)  # Give time for subscription to work
                
                try:
                    while True:
                        await asyncio.sleep(args.interval)
                        update_result = await client.get_updates(session_id)
                        
                        if update_result.get("status") == "success":
                            updates = update_result.get("updates", {})
                            total_spots = updates.get("total_spots", 0)
                            unique_stations = updates.get("unique_stations", 0)
                            
                            print(f"\n[{time.time():.1f}] Total spots: {total_spots}, Unique stations: {unique_stations}")
                            
                            if total_spots > 0:
                                stations = updates.get("stations", {})
                                for callsign, spots in stations.items():
                                    for spot in spots:
                                        print(f"  {callsign}: {spot.get('frequency', 0):.3f} MHz - {spot.get('mode', 'Unknown')} - SNR: {spot.get('snr', 0)} dB - {spot.get('country', 'Unknown')}")
                        else:
                            print(f"Error getting updates: {update_result.get('message')}")
                            # Continue trying rather than exiting
                            
                except KeyboardInterrupt:
                    print("\nExiting continuous update mode.")
                    if args.auto_stop:
                        stop_result = await client.stop_subscription(session_id)
                        print(f"Stopped subscription: {stop_result}")
        
    except Exception as e:
        print(f"Error in start_subscription: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.stop_server()


async def get_updates(args):
    """Get updates for a session."""
    session_id = args.session or load_last_session()
    if not session_id:
        print("Error: No session ID provided and no saved session found.")
        return
    
    client = PSKReporterSTDIOClient()
    
    try:
        await client.start_server()
        
        result = await client.get_updates(session_id)
        
        if result.get("status") == "success":
            updates = result.get("updates", {})
            total_spots = updates.get("total_spots", 0)
            unique_stations = updates.get("unique_stations", 0)
            stations = updates.get("stations", {})
            
            print(f"Total spots: {total_spots}")
            print(f"Unique stations: {unique_stations}")
            
            if total_spots > 0:
                print("\nStations heard:")
                for callsign, spots in stations.items():
                    print(f"  {callsign}:")
                    for spot in spots:
                        print(f"    {spot.get('frequency', 0):.3f} MHz - {spot.get('mode', 'Unknown')} - SNR: {spot.get('snr', 0)} dB - {spot.get('country', 'Unknown')} - Grid: {spot.get('locator', 'Unknown')}")
        else:
            print(f"Error: {result.get('message')}")
        
    finally:
        await client.stop_server()


async def stop_subscription(args):
    """Stop a subscription."""
    session_id = args.session or load_last_session()
    if not session_id:
        print("Error: No session ID provided and no saved session found.")
        return
    
    client = PSKReporterSTDIOClient()
    
    try:
        await client.start_server()
        
        result = await client.stop_subscription(session_id)
        print("Stop result:", json.dumps(result, indent=2))
        
    finally:
        await client.stop_server()


async def main():
    parser = argparse.ArgumentParser(description="PSK Reporter MCP STDIO Client")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # START command
    start_parser = subparsers.add_parser("start", help="Start a subscription")
    start_parser.add_argument("--band", help="Band filter (e.g., 20m, 40m)")
    start_parser.add_argument("--mode", help="Mode filter (e.g., FT8, FT4)")
    start_parser.add_argument("--country", help="Sender country code")
    start_parser.add_argument("--locator", help="Sender grid locator prefix")
    start_parser.add_argument("--callsign", help="Sender callsign or pattern")
    start_parser.add_argument("--owner-filter", action="store_true", help="Apply owner filter")
    start_parser.add_argument("--continuous", action="store_true", help="Continuously get updates")
    start_parser.add_argument("--interval", type=int, default=5, help="Update interval in seconds (default: 5)")
    start_parser.add_argument("--auto-stop", action="store_true", help="Stop subscription when exiting continuous mode")
    start_parser.add_argument("--server", help="Path to server file", default="pskreporter_mcp_server_debug.py")
    
    # GET-UPDATES command
    get_parser = subparsers.add_parser("get-updates", help="Get updates for a session")
    get_parser.add_argument("--session", help="Session ID (if omitted, uses last session)")
    get_parser.add_argument("--server", help="Path to server file", default="pskreporter_mcp_server_debug.py")
    
    # STOP command
    stop_parser = subparsers.add_parser("stop", help="Stop a subscription")
    stop_parser.add_argument("--session", help="Session ID (if omitted, uses last session)")
    stop_parser.add_argument("--server", help="Path to server file", default="pskreporter_mcp_server_debug.py")
    
    args = parser.parse_args()
    
    # Set the server path if provided
    server_path = getattr(args, 'server', 'pskreporter_mcp_server_debug.py')
    
    if args.command == "start":
        client = PSKReporterSTDIOClient(server_path)
        await start_subscription(args)
    elif args.command == "get-updates":
        client = PSKReporterSTDIOClient(server_path)
        await get_updates(args)
    elif args.command == "stop":
        client = PSKReporterSTDIOClient(server_path)
        await stop_subscription(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())