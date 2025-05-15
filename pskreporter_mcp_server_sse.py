#!/usr/bin/env python
# pskreporter_mcp_sse_client.py
"""
PSK Reporter MCP Client for SSE transport

This client works with the SSE transport version of the MCP server.
"""

import argparse
import json
import time
import asyncio
from typing import Dict, Any, Optional

import httpx


# Constants
SERVER_URL = "http://localhost:8000/mcp"
TIMEOUT = 30  # seconds


class PSKReporterSSEClient:
    def __init__(self, server_url: str = SERVER_URL):
        self.server_url = server_url
        self.client_info = {
            "name": "pskreporter-client", 
            "version": "1.0.0"
        }
        
    async def initialize_session(self) -> httpx.AsyncClient:
        """Initialize the SSE connection with the MCP server."""
        client = httpx.AsyncClient(timeout=httpx.Timeout(TIMEOUT))
        
        # Initial handshake
        init_msg = {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": True}},
                "clientInfo": self.client_info
            }
        }
        
        # Send POST request to establish SSE connection
        response = await client.post(
            f"{self.server_url}/sse",
            json=init_msg,
            headers={
                "Accept": "text/event-stream",
                "Cache-Control": "no-cache"
            }
        )
        response.raise_for_status()
        return client
        
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> Dict[str, Any]:
        """Call a tool on the MCP server via SSE."""
        client = await self.initialize_session()
        
        try:
            call_msg = {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": tool_name,
                    "arguments": arguments
                }
            }
            
            response = await client.post(
                f"{self.server_url}/sse",
                json=call_msg,
                headers={"Content-Type": "application/json"}
            )
            response.raise_for_status()
            
            # Parse the response
            result = response.json()
            if "error" in result:
                return {"status": "error", "message": result["error"]}
            return result.get("result", {})
            
        except httpx.HTTPStatusError as e:
            return {"status": "error", "message": f"HTTP error: {e}"}
        except Exception as e:
            return {"status": "error", "message": f"Error: {e}"}
        finally:
            await client.aclose()

    async def start_subscription(self, **kwargs) -> Dict[str, Any]:
        """Start a subscription."""
        arguments = {k: v for k, v in kwargs.items() if v is not None}
        return await self.call_tool("start_subscription", arguments)
    
    async def get_updates(self, session_id: str) -> Dict[str, Any]:
        """Get updates for a session."""
        return await self.call_tool("get_updates", {"session_id": session_id})
    
    async def stop_subscription(self, session_id: str) -> Dict[str, Any]:
        """Stop a subscription."""
        return await self.call_tool("stop_subscription", {"session_id": session_id})


async def start_subscription(args) -> None:
    """Start a subscription with the specified filters."""
    client = PSKReporterSSEClient()
    
    result = await client.start_subscription(
        band=args.band,
        mode=args.mode,
        sendercountry=args.country,
        senderlocator=args.locator,
        sendercall=args.callsign,
        apply_owner_filter=args.owner_filter
    )
    
    # Display the result
    if result.get("status") == "success":
        print(f"Subscription started successfully!")
        print(f"Session ID: {result.get('session_id')}")
        print(f"MQTT Topic: {result.get('topic')}")
        
        # Store session ID in a file for easy retrieval
        with open("last_session.txt", "w") as f:
            f.write(result.get('session_id'))
            
        print(f"Session ID saved to last_session.txt")
        
        # If the user requested continuous updates, enter a loop
        if args.continuous:
            print("\nStarting continuous update mode. Press Ctrl+C to exit.")
            try:
                while True:
                    await get_updates_for_session(result.get('session_id'), client)
                    await asyncio.sleep(args.interval)
            except KeyboardInterrupt:
                print("\nExiting continuous update mode.")
                if args.auto_stop:
                    await client.stop_subscription(result.get('session_id'))
    else:
        print(f"Error starting subscription: {result.get('message')}")


async def get_updates_for_session(session_id: str, client: Optional[PSKReporterSSEClient] = None) -> int:
    """Get updates for a specific session ID."""
    if client is None:
        client = PSKReporterSSEClient()
    
    result = await client.get_updates(session_id)
    
    if result.get("status") == "success":
        updates = result.get("updates", {})
        total_spots = updates.get("total_spots", 0)
        unique_stations = updates.get("unique_stations", 0)
        stations = updates.get("stations", {})
        
        print("\n" + "="*50)
        print(f"Updates for session {session_id}")
        print(f"Total spots: {total_spots}")
        print(f"Unique stations: {unique_stations}")
        
        if total_spots > 0:
            print("\nStations heard:")
            for callsign, spots in stations.items():
                print(f"  {callsign}:")
                for spot in spots:
                    print(f"    {spot.get('frequency', 0):.3f} MHz - {spot.get('mode', 'Unknown')} - SNR: {spot.get('snr', 0)} dB - {spot.get('country', 'Unknown')} - Grid: {spot.get('locator', 'Unknown')}")
        print("="*50)
        return total_spots
    else:
        print(f"Error getting updates: {result.get('message')}")
        return 0


async def stop_subscription_by_id(session_id: str) -> None:
    """Stop a subscription by its session ID."""
    client = PSKReporterSSEClient()
    result = await client.stop_subscription(session_id)
    
    if result.get("status") == "success":
        print(f"Successfully stopped session {session_id}")
    else:
        print(f"Error stopping session: {result.get('message')}")


def load_last_session() -> Optional[str]:
    """Load the last session ID from file if it exists."""
    try:
        with open("last_session.txt", "r") as f:
            return f.read().strip()
    except FileNotFoundError:
        return None


async def main():
    # Create argument parser
    parser = argparse.ArgumentParser(description="PSK Reporter MCP SSE Client")
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")
    
    # START command
    start_parser = subparsers.add_parser("start", help="Start a subscription")
    start_parser.add_argument("--band", help="Band filter (e.g., 20m, 40m)")
    start_parser.add_argument("--mode", help="Mode filter (e.g., FT8, FT4, JS8)")
    start_parser.add_argument("--country", help="Sender country code")
    start_parser.add_argument("--locator", help="Sender grid locator prefix")
    start_parser.add_argument("--callsign", help="Sender callsign or pattern")
    start_parser.add_argument("--owner-filter", action="store_true", help="Apply owner filter")
    start_parser.add_argument("--continuous", action="store_true", help="Continuously get updates")
    start_parser.add_argument("--interval", type=int, default=5, help="Update interval in seconds (default: 5)")
    start_parser.add_argument("--auto-stop", action="store_true", help="Stop subscription when exiting continuous mode")
    
    # GET-UPDATES command
    get_parser = subparsers.add_parser("get-updates", help="Get updates for a session")
    get_parser.add_argument("--session", help="Session ID (if omitted, uses last session)")
    get_parser.add_argument("--continuous", action="store_true", help="Continuously get updates")
    get_parser.add_argument("--interval", type=int, default=5, help="Update interval in seconds (default: 5)")
    get_parser.add_argument("--auto-stop", action="store_true", help="Stop subscription when exiting continuous mode")
    
    # STOP command
    stop_parser = subparsers.add_parser("stop", help="Stop a subscription")
    stop_parser.add_argument("--session", help="Session ID (if omitted, uses last session)")
    
    # Parse arguments
    args = parser.parse_args()
    
    # Execute command
    if args.command == "start":
        await start_subscription(args)
    elif args.command == "get-updates":
        session_id = args.session or load_last_session()
        if not session_id:
            print("Error: No session ID provided and no saved session found.")
            return
        
        client = PSKReporterSSEClient()
        if args.continuous:
            print(f"Starting continuous updates for session {session_id}. Press Ctrl+C to exit.")
            try:
                while True:
                    await get_updates_for_session(session_id, client)
                    await asyncio.sleep(args.interval)
            except KeyboardInterrupt:
                print("\nExiting continuous update mode.")
                if args.auto_stop:
                    await client.stop_subscription(session_id)
        else:
            await get_updates_for_session(session_id, client)
    elif args.command == "stop":
        session_id = args.session or load_last_session()
        if not session_id:
            print("Error: No session ID provided and no saved session found.")
            return
        
        await stop_subscription_by_id(session_id)
    else:
        parser.print_help()


if __name__ == "__main__":
    asyncio.run(main())