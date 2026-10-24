# Deriv MCP Server

Gives Claude, Cursor, ChatGPT and other AI assistants **real-time Deriv market data** (forex, synthetics, gold, etc.).

## Tools available

| Tool | Description |
|------|-------------|
| `get_active_symbols` | List active symbols (forex, synthetic_index, commodities...) |
| `get_ticks` | Latest live ticks for a symbol |
| `get_ticks_history` | Historical ticks or OHLC candles |
| `get_account_balance` | Your account balance (needs token) |
| `get_symbol_info` | Details about one symbol |

## Quick Start (Local)

### 1. Install

```bash
cd deriv-mcp
python -m venv venv
source venv/bin/activate          # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Set your token (optional but recommended)

```bash
export DERIV_API_TOKEN="your_token_here"
```

(The token is already hardcoded in `server.py` for convenience. For better security, remove it from the file and use the environment variable.)

### 3. Run the server

```bash
python server.py
```

### 4. Connect to Claude Desktop

Edit your Claude config file:

- **macOS**: `~/Library/Application Support/Claude/claude_desktop_config.json`
- **Windows**: `%APPDATA%\Claude\claude_desktop_config.json`

Add:

```json
{
  "mcpServers": {
    "deriv": {
      "command": "python",
      "args": ["/full/path/to/deriv-mcp/server.py"],
      "env": {
        "DERIV_API_TOKEN": "your_token_here"
      }
    }
  }
}
```

Restart Claude Desktop.

### 5. Connect to Cursor

Add to `.cursor/mcp.json` or global settings:

```json
{
  "mcpServers": {
    "deriv": {
      "command": "python",
      "args": ["/full/path/to/deriv-mcp/server.py"],
      "env": {
        "DERIV_API_TOKEN": "your_token_here"
      }
    }
  }
}
```

## Example questions you can ask the AI

- "What is the current EURUSD price on Deriv?"
- "Give me the last 20 ticks of frxXAUUSD"
- "Show me 5-minute candles for GBPJPY for the last 50 bars"
- "List all active forex symbols"
- "What is my account balance?"

## Symbol examples

| Symbol | Meaning |
|--------|---------|
| `frxEURUSD` | EUR/USD |
| `frxGBPUSD` | GBP/USD |
| `frxXAUUSD` | Gold |
| `frxGBPJPY` | GBP/JPY |
| `R_100` | Volatility 100 Index |
| `1HZ100V` | Volatility 100 (1s) |

## Security Note

The token you provided has been placed in the code for easy testing.  
**For production use**, remove the hardcoded token and only pass it via environment variable.
