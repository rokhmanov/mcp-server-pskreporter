# PSK Reporter MCP Server

A Model Context Protocol (MCP) server that provides real-time amateur radio propagation data from PSKReporter via Claude Desktop.

## Features

- **Real-time Propagation Data**: Collect live spots from amateur radio stations worldwide
- **Advanced Filtering**: Filter by band, mode, callsign, location, and country
- **DXCC Entity Support**: Full country/territory mapping for precise filtering
- **Threaded Architecture**: Non-blocking MQTT collection for responsive performance

## Installation

### Prerequisites

- Python 3.13 or higher
- uv package manager
- Claude Desktop application

### Setup

1. **Clone or download this repository**
   ```bash
   git clone <your-repo-url>
   cd mcp-server-pskreporter
   ```

2. **Install dependencies with uv**
   ```bash
   uv sync
   ```

3. **Verify the server works**
   ```bash
   uv run python pskreporter_mcp_server.py
   ```
   The server should start and be ready to accept MCP connections.

## Adding to Claude Desktop

**Important**: Both methods require that Claude Desktop knows the **working directory** where your `pskreporter_mcp_server.py` file is located. This is the folder containing your project files.

### Method 1: Using Claude Desktop UI (Recommended)

1. Open Claude Desktop
2. Go to **Settings** → **MCP Servers**
3. Click **Add Server**
4. Configure the server:
   - **Name**: `pskreporter`
   - **Command**: `uv`
   - **Arguments**: `run python pskreporter_mcp_server.py`
   - **Working Directory**: `C:\Users\rokhm\git\mcp-server-pskreporter` (your project folder)
5. Click **Save**

**What Claude Desktop does**: It will run `uv run python pskreporter_mcp_server.py` from your project directory, so it can find the `pskreporter_mcp_server.py` file and all other project files.

### Method 2: Using Configuration File

1. **Edit the configuration file** to match your system:
   - Open `claude_desktop_config.json`
   - Update the `cwd` path to match your project directory
   - For Windows, use double backslashes: `C:\\Users\\rokhm\\git\\mcp-server-pskreporter`

2. **Copy the configuration file** to Claude Desktop's configuration directory:
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Linux**: `~/.config/Claude/claude_desktop_config.json`

3. Restart Claude Desktop

**Note**: The `claude_desktop_config.json` file in this repository is pre-configured for your current path. If you move the project, update the `cwd` path accordingly.

### Method 3: Development Mode

For development and testing:
```bash
uv run mcp dev pskreporter_mcp_server.py
```

## Usage

Once connected to Claude Desktop, you can use these tools:

### `get_spots`
Collect real-time amateur radio propagation spots with filtering options.

**Parameters:**
- `band`: Amateur radio band (e.g., "20m", "40m", "80m")
- `mode`: Operating mode (e.g., "FT8", "FT4", "CW")
- `sendercall`: Specific station callsign
- `duration`: Collection time in seconds (5-10)

**Examples:**
- "Show me FT8 activity on 20m"
- "Find stations from Japan on 40m"
- "What bands is W9KM operating on?"

### `get_dxcc_entities`
Get the complete list of DXCC entities (country codes and names).

### `search_dxcc_entities`
Search for DXCC entities by country name.

**Example:**
- "Find the entity code for Japan"

## Data Source

This server connects to the PSKReporter MQTT feed at `mqtt.pskreporter.info` to retrieve live propagation data from amateur radio stations worldwide.

## Troubleshooting

### Common Issues

1. **Server won't start**
   - Ensure Python 3.13+ is installed
   - Ensure uv is installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Check dependencies are installed: `uv sync`

2. **No spots collected**
   - Increase the `duration` parameter (up to 10 seconds)
   - Use broader filters (fewer parameters)
   - Check your internet connection

3. **Claude Desktop can't connect**
   - Verify the working directory path is correct
   - Ensure the server starts successfully when run manually: `uv run python pskreporter_mcp_server.py`
   - Check Claude Desktop logs for error messages

4. **"File not found" errors**
   - Make sure the working directory points to the folder containing `pskreporter_mcp_server.py`
   - Verify all project files are in the same directory

### Debug Information

The server creates a debug log file `mcp_server_debug.log` with detailed information about:
- MQTT connection status
- Spot collection progress
- Error messages and stack traces

## Development

This project uses `uv` for dependency management. Key commands:

- `uv sync` - Install dependencies
- `uv run python pskreporter_mcp_server.py` - Run the server
- `uv run mcp dev pskreporter_mcp_server.py` - Run in development mode

---
73!
Andriy
W9KM
