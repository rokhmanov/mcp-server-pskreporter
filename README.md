# PSK Reporter MCP Server

A Model Context Protocol (MCP) server that provides real-time amateur radio propagation data from PSKReporter via Claude Desktop.

## Features

- **Real-time Propagation Data**: Collect live spots from amateur radio stations worldwide
- **Advanced Filtering**: Filter by band, mode, callsign, location, and country
- **DXCC Entity Support**: Full country/territory mapping with intelligent name variations
- **MCP Resource**: Discover available countries and their common variations
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

3. **Choose your installation method:**

   **Option A: Development Mode (For direct command usage)**
   ```bash
   uv pip install -e .
   ```
   This installs the package in development mode in the local virtual environment, making the `pskreporter-mcp-server` command available within this project's environment. Use this if you want to run the command directly from the project directory.

   **Option B: Project-based execution (For Claude Desktop - No installation needed)**
   ```bash
   uv run --project . pskreporter-mcp-server
   ```
   This runs the server directly from the project directory without installation. This is what Claude Desktop uses by default.

4. **Verify the server works**
   
   If you used Option A (development mode):
   ```bash
   # Make sure you're in the project directory
   pskreporter-mcp-server
   ```
   
   If you used Option B (project-based):
   ```bash
   uv run --project . pskreporter-mcp-server
   ```
   
   The server should start and be ready to accept MCP connections.

## Adding to Claude Desktop

### Method 1: Using Configuration File (Recommended)

1. **Copy the configuration file** to Claude Desktop's configuration directory:
   - **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`
   - **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - **Linux**: `~/.config/Claude/claude_desktop_config.json`

2. **Update the path** in `claude_desktop_config.json` to match your system:
   ```json
   {
     "mcpServers": {
       "pskreporter": {
         "command": "uv",
         "args": ["run", "--project", "C:\\Users\\rokhm\\git\\mcp-server-pskreporter", "pskreporter-mcp-server"],
         "env": {}
       }
     }
   }
   ```

3. **Restart Claude Desktop**

**Note**: The `claude_desktop_config.json` file in this repository is pre-configured for the current path. If you move the project, update the path in the `--project` argument accordingly.

### Method 2: Using Claude Desktop UI

1. Open Claude Desktop
2. Go to **Settings** → **MCP Servers**
3. Click **Add Server**
4. Configure the server:
   - **Name**: `pskreporter`
   - **Command**: `uv`
   - **Arguments**: `run --project C:\Users\rokhm\git\mcp-server-pskreporter pskreporter-mcp-server`
   - **Working Directory**: `C:\Users\rokhm\git\mcp-server-pskreporter` (your project folder)
5. Click **Save**

### Method 3: Alternative Commands

You can also run the server using these alternative methods:

**Direct Python execution:**
```bash
python -m pskreporter_mcp_server
```

**Using uv run:**
```bash
uv run pskreporter-mcp-server
```

**Development mode:**
```bash
uv run mcp dev pskreporter_mcp_server.py
```

## Usage

Once connected to Claude Desktop, you can use these tools and resources:

### `get_spots` Tool
Collect real-time amateur radio propagation spots with filtering options.

**Parameters:**
- `band`: Amateur radio band (e.g., "20m", "40m", "80m", "160m", "10m", "15m", "17m", "30m", "12m", "6m", "2m")
- `mode`: Operating mode (e.g., "FT8", "FT4", "CW", "SSB", "PSK31", "RTTY")
- `sendercall`: Specific station callsign (e.g., "W9KM", "JA1ABC")
- `receivercall`: Callsign of receiving station
- `senderlocator`: Maidenhead grid locator of sending station (e.g., "EN51", "JO20")
- `receiverlocator`: Maidenhead grid locator of receiving station
- `sendercountry`: Country name for sender's country (e.g., "Japan", "USA", "Germany")
- `receivercountry`: Country name for receiver's country
- `duration`: Collection time in seconds (5-30, default: 10)

**Country Name Features:**
- **Case-insensitive**: "japan", "JAPAN", "Japan" all work the same
- **Partial matching**: "swains" matches "Swains I.", "korea" matches "Republic of Korea"
- **Common variations**: "USA", "UK", "Germany" are automatically mapped to their full names
- **340+ entities**: Full DXCC entity support for worldwide coverage

**Examples:**
- "Show me FT8 activity on 20m from Japan"
- "Find USA stations on 40m"
- "What bands is W9KM operating on?"
- "Show me stations from Germany on 80m"

### `dxcc_entities` Resource
Discover available countries and their variations for better filtering.

**Resource Features:**
- **Complete Entity List**: All 340 DXCC entities with official names
- **Name Variations**: Common variations for each country (e.g., "USA" for "United States of America")
- **Usage Examples**: Ready-to-use examples for the `get_spots` tool
- **Search Tips**: Guidance for effective country name usage

**How to Use:**
- Browse all available countries and territories
- See common variations for each country
- Get exact names to use in `get_spots` parameters
- Discover new DXCC entities you might not know about

**Example Resource Data:**
```json
{
  "code": "291",
  "name": "United States of America",
  "name_variations": ["United States", "USA", "US", "America"]
}
```

## Country Name Discovery

The `dxcc_entities` resource provides comprehensive country information:

- **Official Names**: Use exact DXCC entity names for best results
- **Common Variations**: Popular abbreviations and alternative names
- **Case Flexibility**: All names work regardless of capitalization
- **Partial Matching**: Find countries even with incomplete names

**Popular Examples:**
- **United States**: "USA", "US", "America", "United States of America"
- **United Kingdom**: "UK", "Great Britain", "Britain", "England"
- **Germany**: "Germany", "Deutschland", "DE"
- **Japan**: "Japan" (no common variations)
- **Swains Island**: "Swains", "Swains I.", "Swains Island"

## Data Source

This server connects to the PSKReporter MQTT feed at `mqtt.pskreporter.info` to retrieve live propagation data from amateur radio stations worldwide.

## Troubleshooting

### Common Issues

1. **Server won't start**
   - Ensure Python 3.13+ is installed
   - Ensure uv is installed: `curl -LsSf https://astral.sh/uv/install.sh | sh`
   - Check dependencies are installed: `uv sync`

2. **No spots collected**
   - Increase the `duration` parameter (up to 30 seconds)
   - Use broader filters (fewer parameters)
   - Check your internet connection

3. **Country name not found**
   - Use the `dxcc_entities` resource to find exact country names
   - Try common variations (e.g., "USA" instead of "United States of America")
   - Check for typos and try partial matches

4. **Claude Desktop can't connect**
   - Verify the path in `claude_desktop_config.json` is correct
   - Ensure the server starts successfully when run manually: `uv run pskreporter-mcp-server`
   - Check Claude Desktop logs for error messages

5. **"File not found" errors**
   - Make sure the working directory points to the folder containing `pskreporter_mcp_server.py`
   - Verify all project files are in the same directory

6. **"program not found" or "Failed to spawn" errors**
   - If you get "Failed to spawn 'pskreporter-mcp-server' caused by: program not found" when running the command directly, you need to install the package in development mode:
     ```bash
     uv pip install -e .
     ```
   - After installation, the `pskreporter-mcp-server` command will be available within the project's virtual environment
   - **Note**: Claude Desktop uses `uv run --project` which doesn't require installation - the provided `claude_desktop_config.json` works without any additional setup

### Debug Information

The server creates a debug log file `mcp_server_debug.log` with detailed information about:
- MQTT connection status
- Spot collection progress
- Country name resolution
- Error messages and stack traces

## Development

This project uses `uv` for dependency management. Key commands:

- `uv sync` - Install dependencies
- `uv run pskreporter-mcp-server` - Run the server
- `uv run --project C:\Users\rokhm\git\mcp-server-pskreporter pskreporter-mcp-server` - Run from any directory
- `python -m pskreporter_mcp_server` - Run as Python module

## Configuration

### Claude Desktop Configuration

The `claude_desktop_config.json` file is pre-configured to use `uv run --project`:

```json
{
  "mcpServers": {
    "pskreporter": {
      "command": "uv",
      "args": ["run", "--project", "C:\\Users\\rokhm\\git\\mcp-server-pskreporter", "pskreporter-mcp-server"],
      "env": {}
    }
  }
}
```

**Key points:**
- Uses `uv run --project` command for direct project execution
- `--project` argument points to the local project directory
- No pre-installation required (uv handles dependencies automatically)
- The executable name is `pskreporter-mcp-server` (with hyphens)

### DXCC Entities Configuration

The server uses a YAML-based configuration for DXCC entities (`dxcc_entities.yaml`) that provides:

- **Easy Maintenance**: Country names and variations are stored in a human-readable YAML file
- **Flexible Updates**: Add or modify country variations without touching code
- **Structured Data**: Clear separation between canonical names and common variations

**File Structure:**
```yaml
dxcc_entities:
  "291":
    canonical_name: "United States of America"
    name_variations: ["USA", "US", "United States", "America"]
  "339":
    canonical_name: "Japan"
    name_variations: []
```

**Adding Country Variations:**
To add variations for a country, simply edit the `dxcc_entities.yaml` file:

1. Find the country by its DXCC code
2. Add variations to the `name_variations` array
3. Restart the server to apply changes

**Example:**
```yaml
"339":
  canonical_name: "Japan"
  name_variations: ["Nippon", "Nihon"]
```

The server automatically loads these changes on startup, making it easy to maintain and extend country name support.

---
73!
Andriy
W9KM