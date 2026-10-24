#!/usr/bin/env python3
"""
Deriv MCP Server
----------------
Gives AI assistants (Claude, Cursor, ChatGPT, etc.) real-time access to Deriv market data.

Tools provided:
- get_active_symbols
- get_ticks (live stream snapshot)
- get_ticks_history
- get_account_balance (requires token)

Usage (local stdio):
  python server.py

Then add to Claude Desktop / Cursor config.
"""

import asyncio
import json
import os
import logging
from typing import Any, Optional
from contextlib import asynccontextmanager

import websockets
from mcp.server.fastmcp import FastMCP

# ====================== CONFIG ======================
# Your Deriv Personal Access Token (PAT)
DERIV_TOKEN = os.getenv("DERIV_API_TOKEN")

# Public WebSocket endpoint (no auth needed for market data)
WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"

# For authenticated endpoints you can also use the newer API
# WS_URL_AUTH = "wss://api.derivws.com/trading/v1/options/ws/public"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("deriv-mcp")

HOST = os.getenv("HOST", "0.0.0.0")
PORT = int(os.getenv("PORT", "8000"))

mcp = FastMCP("Deriv Market Data", host=HOST, port=PORT)

# ====================== WebSocket Helper ======================

class DerivClient:
    def __init__(self, token: Optional[str] = None):
        self.token = token
        self.ws = None
        self._req_id = 0

    async def connect(self):
        self.ws = await websockets.connect(WS_URL)
        if self.token:
            # Authorize
            await self.send({"authorize": self.token})
            resp = await self.recv()
            if "error" in resp:
                logger.warning(f"Authorize failed: {resp['error']}")
            else:
                logger.info("Authorized successfully")

    async def send(self, payload: dict):
        self._req_id += 1
        payload["req_id"] = self._req_id
        await self.ws.send(json.dumps(payload))
        return self._req_id

    async def recv(self) -> dict:
        raw = await self.ws.recv()
        return json.loads(raw)

    async def request(self, payload: dict, timeout: float = 10.0) -> dict:
        await self.send(payload)
        try:
            resp = await asyncio.wait_for(self.recv(), timeout=timeout)
            return resp
        except asyncio.TimeoutError:
            return {"error": {"message": "Request timed out"}}

    def is_closed(self) -> bool:
        if self.ws is None:
            return True
        state = getattr(self.ws, "state", None)  # websockets >= 14
        if state is not None:
            return state.name != "OPEN"
        return bool(getattr(self.ws, "closed", False))  # legacy

    async def close(self):
        if self.ws:
            await self.ws.close()


# Global client (reused)
_client: Optional[DerivClient] = None

async def get_client() -> DerivClient:
    global _client
    if _client is None or _client.ws is None or _client.is_closed():
        _client = DerivClient(DERIV_TOKEN)
        await _client.connect()
    return _client


# ====================== TOOLS ======================

@mcp.tool()
async def get_active_symbols(market: str = "forex") -> dict:
    """
    Get list of currently active trading symbols on Deriv.
    
    Args:
        market: Filter by market type. Options: forex, synthetic_index, commodities, cryptocurrency, indices, or "all"
    """
    client = await get_client()
    payload = {
        "active_symbols": "brief",
        "product_type": "basic"
    }
    resp = await client.request(payload)
    
    if "error" in resp:
        return {"error": resp["error"]}
    
    symbols = resp.get("active_symbols", [])
    
    if market.lower() != "all":
        symbols = [s for s in symbols if s.get("market") == market.lower() or 
                   market.lower() in s.get("market_display_name", "").lower()]
    
    # Simplify output
    result = []
    for s in symbols[:50]:  # limit to keep response small
        result.append({
            "symbol": s.get("symbol"),
            "display_name": s.get("display_name"),
            "market": s.get("market"),
            "submarket": s.get("submarket"),
            "pip": s.get("pip"),
            "spot": s.get("spot"),
        })
    
    return {
        "count": len(result),
        "symbols": result
    }


@mcp.tool()
async def get_ticks(symbol: str = "frxEURUSD", count: int = 5) -> dict:
    """
    Get the latest live ticks (price updates) for a symbol.
    
    Args:
        symbol: Deriv symbol name, e.g. frxEURUSD, frxGBPUSD, R_100, 1HZ100V, frxXAUUSD
        count: How many recent ticks to return (1-20)
    """
    client = await get_client()
    
    # First get a short history so we have something immediate
    history_resp = await client.request({
        "ticks_history": symbol,
        "end": "latest",
        "count": min(count, 20),
        "style": "ticks"
    })
    
    if "error" in history_resp:
        return {"error": history_resp["error"], "hint": "Check if the symbol is correct. Use get_active_symbols first."}
    
    history = history_resp.get("history", {})
    prices = history.get("prices", [])
    times = history.get("times", [])
    
    ticks = []
    for p, t in zip(prices, times):
        ticks.append({
            "quote": p,
            "epoch": t,
            "time": __import__("datetime").datetime.utcfromtimestamp(t).isoformat() + "Z"
        })
    
    return {
        "symbol": symbol,
        "ticks": ticks,
        "latest": ticks[-1] if ticks else None
    }


@mcp.tool()
async def get_ticks_history(
    symbol: str = "frxEURUSD",
    count: int = 100,
    granularity: int = 60
) -> dict:
    """
    Get historical OHLC or tick data.
    
    Args:
        symbol: e.g. frxEURUSD, frxXAUUSD, R_100
        count: Number of candles/ticks (max ~5000)
        granularity: Candle size in seconds. 60=1m, 300=5m, 900=15m, 3600=1h, 86400=1d.
                     Use 0 or omit for raw ticks.
    """
    client = await get_client()
    
    payload = {
        "ticks_history": symbol,
        "end": "latest",
        "count": min(count, 5000),
        "style": "candles" if granularity and granularity > 0 else "ticks",
    }
    if granularity and granularity > 0:
        payload["granularity"] = granularity
    
    resp = await client.request(payload, timeout=15)
    
    if "error" in resp:
        return {"error": resp["error"]}
    
    if "candles" in resp:
        return {
            "symbol": symbol,
            "granularity": granularity,
            "candles": resp["candles"]
        }
    elif "history" in resp:
        return {
            "symbol": symbol,
            "style": "ticks",
            "prices": resp["history"].get("prices", []),
            "times": resp["history"].get("times", [])
        }
    return resp


@mcp.tool()
async def get_account_balance() -> dict:
    """
    Get the current account balance (requires a valid API token with read permission).
    """
    client = await get_client()
    resp = await client.request({"balance": 1, "subscribe": 0})
    
    if "error" in resp:
        return {"error": resp["error"], "hint": "Make sure your token has 'Read' permission and is authorized."}
    
    balance = resp.get("balance", {})
    return {
        "balance": balance.get("balance"),
        "currency": balance.get("currency"),
        "loginid": balance.get("loginid"),
    }


@mcp.tool()
async def get_symbol_info(symbol: str) -> dict:
    """
    Get detailed information about one specific symbol.
    """
    client = await get_client()
    resp = await client.request({
        "active_symbols": "full",
        "product_type": "basic"
    })
    
    if "error" in resp:
        return {"error": resp["error"]}
    
    for s in resp.get("active_symbols", []):
        if s.get("symbol") == symbol:
            return {
                "symbol": s.get("symbol"),
                "display_name": s.get("display_name"),
                "market": s.get("market"),
                "submarket": s.get("submarket"),
                "pip": s.get("pip"),
                "spot": s.get("spot"),
                "quote": s.get("quote"),
                "exchange_is_open": s.get("exchange_is_open"),
                "is_trading_suspended": s.get("is_trading_suspended"),
            }
    
    return {"error": f"Symbol '{symbol}' not found"}


# ====================== RUN ======================

if __name__ == "__main__":
    transport = os.getenv("MCP_TRANSPORT", "stdio").lower()
    logger.info(f"Starting Deriv MCP | transport={transport} host={HOST} port={PORT}")

    if transport == "sse":
        mcp.run(transport="sse")
    elif transport in ("http", "streamable-http"):
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")
