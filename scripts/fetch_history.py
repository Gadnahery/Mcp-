"""Download exact 15M and 5M OHLC history from Deriv for replay.py (run where you have internet).

  python scripts/fetch_history.py frxXAUUSD 2026-10-23 2026-10-24 history.json
Pages through Deriv's ticks_history using start/end epochs (max 5000 candles per request).
"""
import asyncio
import datetime as dt
import json
import sys

import websockets

URLS = [
    "wss://api.derivws.com/trading/v1/options/ws/public",
    "wss://ws.derivws.com/websockets/v3?app_id=1089",
]


async def fetch(symbol: str, gran: int, start: int, end: int) -> list[dict]:
    out: dict[int, dict] = {}
    for url in URLS:
        try:
            async with websockets.connect(url, open_timeout=10) as ws:
                cursor = start
                while cursor < end:
                    await ws.send(json.dumps({"ticks_history": symbol, "start": cursor, "end": end,
                                              "count": 5000, "style": "candles", "granularity": gran}))
                    resp = json.loads(await ws.recv())
                    if resp.get("error"):
                        raise RuntimeError(resp["error"].get("message"))
                    candles = resp.get("candles", [])
                    if not candles:
                        break
                    for c in candles:
                        out[int(c["epoch"])] = {k: (int(c[k]) if k == "epoch" else float(c[k]))
                                                for k in ("epoch", "open", "high", "low", "close")}
                    nxt = int(candles[-1]["epoch"]) + gran
                    if nxt <= cursor:
                        break
                    cursor = nxt
            return [out[k] for k in sorted(out)]
        except Exception as exc:
            print(f"{url} failed: {exc}", file=sys.stderr)
    raise SystemExit("All Deriv endpoints failed")


def epoch(day: str) -> int:
    return int(dt.datetime.fromisoformat(day).replace(tzinfo=dt.timezone.utc).timestamp())


if __name__ == "__main__":
    symbol, d0, d1, path = sys.argv[1:5]
    s, e = epoch(d0), epoch(d1)
    data = {
        "symbol": symbol,
        "m15": asyncio.run(fetch(symbol, 900, s, e)),
        "m5": asyncio.run(fetch(symbol, 300, s, e)),
        "m1": asyncio.run(fetch(symbol, 60, s, e)),
    }
    json.dump(data, open(path, "w"))
    json.dump(data, open(path, "w"))
    print(f"saved {len(data['m15'])} x 15M, {len(data['m5'])} x 5M and {len(data['m1'])} x 1M candles to {path}")
