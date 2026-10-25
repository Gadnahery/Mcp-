"""Small, isolated Deriv candle client for the optional monitoring worker."""
from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import Any

import websockets

logger = logging.getLogger(__name__)
GRANULARITIES = {"1m": 60, "5m": 300, "15m": 900, "1h": 3600}


class DerivMarketData:
    def __init__(self, app_id: str = "1089") -> None:
        # The legacy ws.derivws.com host now rejects connections (HTTP 520), so try the
        # new public market-data endpoint first and keep the legacy one as a fallback.
        self.urls = [
            u for u in (
                os.getenv("DERIV_WS_URL"),
                "wss://api.derivws.com/trading/v1/options/ws/public",
                f"wss://ws.derivws.com/websockets/v3?app_id={app_id}",
            ) if u
        ]
        self._good_url: str | None = None

    async def _request(self, payload: dict[str, Any]) -> dict[str, Any]:
        last_error: Exception | None = None
        for url in ([self._good_url] if self._good_url else []) + [u for u in self.urls if u != self._good_url]:
            try:
                async with websockets.connect(url, open_timeout=10, close_timeout=5) as ws:
                    await ws.send(json.dumps(payload))
                    raw = await asyncio.wait_for(ws.recv(), timeout=15)
                self._good_url = url
                return json.loads(raw)
            except Exception as exc:  # try the next endpoint
                last_error = exc
                logger.warning("Deriv endpoint %s failed: %s", url, exc)
        raise RuntimeError(f"All Deriv endpoints failed: {last_error}")

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
        response = await self._request(payload)
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
