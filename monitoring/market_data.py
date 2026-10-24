"""Small, isolated Deriv candle client for the optional monitoring worker."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

import websockets

logger = logging.getLogger(__name__)
GRANULARITIES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


class DerivMarketData:
    def __init__(self, app_id: str = "1089") -> None:
        self.url = f"wss://ws.derivws.com/websockets/v3?app_id={app_id}"

    async def candles(self, symbol: str, timeframe: str, count: int = 120) -> list[dict[str, Any]]:
        if timeframe not in GRANULARITIES:
            raise ValueError(f"Unsupported timeframe: {timeframe}")
        payload = {
            "ticks_history": symbol,
            "end": "latest",
            "count": min(max(int(count), 60), 500),
            "style": "candles",
            "granularity": GRANULARITIES[timeframe],
        }
        async with websockets.connect(self.url, open_timeout=10, close_timeout=5) as ws:
            await ws.send(json.dumps(payload))
            raw = await asyncio.wait_for(ws.recv(), timeout=15)
            response = json.loads(raw)
        if response.get("error"):
            raise RuntimeError(response["error"].get("message", "Deriv candle request failed"))
        candles = response.get("candles")
        if not isinstance(candles, list):
            raise RuntimeError(f"No candle data returned for {symbol} {timeframe}")
        normalized = []
        for candle in candles:
            try:
                normalized.append({
                    "epoch": int(candle["epoch"]),
                    "open": float(candle["open"]),
                    "high": float(candle["high"]),
                    "low": float(candle["low"]),
                    "close": float(candle["close"]),
                })
            except (KeyError, TypeError, ValueError):
                continue
        return sorted(normalized, key=lambda item: item["epoch"])
