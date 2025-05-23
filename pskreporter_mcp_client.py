#!/usr/bin/env python
# pskreporter_mcp_client.py
"""
PSK Reporter MCP Client - Simplified version for single get_spots method

This client works with the simplified MCP server using stdio transport
"""

import asyncio
import json
import subprocess
import sys
import argparse
import time
from typing import Dict, Any

class PSKReporterSTDIOClient:
    def __init__(self, server_path: str = "pskreporter_mcp_server.py"):
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
    
    async def send_request_raw(self, request: Dict[str, Any], timeout: float = 240) -> Dict[str, Any]:
        """Send a raw JSON-RPC request and get the response."""
        # Send request
        request_json = json.dumps(request) + "\n"
        print(f"Sending request: {json.dumps(request, indent=2)}")
        self.process.stdin.write(request_json.encode())
        await self.process.stdin.drain()
        
        # Read response with better error handling
        try:
            print(f"Waiting for response (timeout: {timeout}s)...")
            # Use dynamic timeout
            response_line = await asyncio.wait_for(self.process.stdout.readline(), timeout=timeout)
            
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
    
    def parse_mcp_response(self, mcp_result: Dict[str, Any]) -> str:
        """Parse MCP response format to extract the actual content."""
        if "isError" in mcp_result and mcp_result["isError"]:
            return "# Error\n\nMCP error in response"
        
        if "content" in mcp_result and mcp_result["content"]:
            # Get the first content item
            content_item = mcp_result["content"][0]
            if content_item.get("type") == "text":
                # Return the text content directly (it's now Markdown)
                return content_item["text"]
        
        return "# Error\n\nUnexpected response format"
    
    async def call_tool(self, tool_name: str, arguments: Dict[str, Any]) -> str:
        """Call a tool using the proper MCP format."""
        
        # Calculate smart timeout based on duration parameter
        duration = arguments.get('duration', 60)  # Default 60 seconds
        smart_timeout = min(duration + 30, 240)   # Never exceed 4 minutes (240 seconds)
        print(f"Using smart timeout: {smart_timeout}s for duration: {duration}s")
        
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
            response = await self.send_request_raw(request, timeout=smart_timeout)
            
            if "error" in response:
                return f"# Error\n\n{response['error']}"
            
            # Parse the MCP response format
            result = response.get("result", {})
            return self.parse_mcp_response(result)
        except Exception as e:
            return f"# Error\n\nCommunication error: {e}"
    
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
    
    async def get_spots(self, **kwargs):
        """Get spots using the simplified method."""
        params = {k: v for k, v in kwargs.items() if v is not None}
        result = await self.call_tool("get_spots", params)
        return result


async def get_spots(client, args):
    """Get spots with the specified filters."""    
    try:
        await client.start_server()
        
        result = await client.get_spots(
            band=args.band,
            mode=args.mode,
            sendercall=args.sendercall,
            receivercall=args.receivercall,
            senderlocator=args.senderlocator,
            receiverlocator=args.receiverlocator,
            sendercountry=args.sendercountry,
            receivercountry=args.receivercountry,
            duration=args.duration
        )
        
        # Result is now Markdown text, just print it
        print(result)
        
    except Exception as e:
        print(f"Error in get_spots: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await client.stop_server()


async def main():
    parser = argparse.ArgumentParser(description="PSK Reporter MCP Client - Complete MQTT Parameters")
    
    # All 8 MQTT topic parameters
    parser.add_argument("--band", help="Band filter (e.g., 20m, 40m)")
    parser.add_argument("--mode", help="Mode filter (e.g., FT8, FT4)")
    parser.add_argument("--sendercall", help="Sender callsign or pattern")
    parser.add_argument("--receivercall", help="Receiver callsign or pattern")
    parser.add_argument("--senderlocator", help="Sender grid locator prefix")
    parser.add_argument("--receiverlocator", help="Receiver grid locator prefix")
    parser.add_argument("--sendercountry", help="Sender country code")
    parser.add_argument("--receivercountry", help="Receiver country code")
    
    # Collection parameters
    parser.add_argument("--duration", type=int, default=60, help="Collection duration in seconds (default: 60)")
    parser.add_argument("--server", help="Path to server file", default="pskreporter_mcp_server.py")
    
    args = parser.parse_args()
    
    # Set the server path if provided
    server_path = getattr(args, 'server', 'pskreporter_mcp_server.py')
    client = PSKReporterSTDIOClient(server_path)
    
    await get_spots(client, args)


if __name__ == "__main__":
    asyncio.run(main())
