"""Optional continuous strategy monitor; run as a separate Render worker/service.

The existing MCP server is left untouched. Configure Telegram and explicitly enable
candidate alerts only after reviewing historical replay results.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

from monitoring.config import Settings
from monitoring.market_data import DerivMarketData, GRANULARITIES
from monitoring.strategy import detect_candidate
from monitoring.telegram import format_candidate, send_telegram

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("strategy-monitor")


def load_state(path: str) -> dict[str, Any]:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return {"sent": {}}


def save_state(path: str, state: dict[str, Any]) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    temp = target.with_suffix(target.suffix + ".tmp")
    temp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    temp.replace(target)


async def run() -> None:
    settings = Settings()
    if not settings.symbols:
        raise RuntimeError("MONITOR_SYMBOLS is empty")
    if settings.telegram_enabled and (not settings.telegram_bot_token or not settings.telegram_chat_id):
        raise RuntimeError("Telegram enabled but bot token/chat ID is missing")

    api = DerivMarketData(settings.deriv_app_id)
    state = load_state(settings.state_path)
    state.setdefault("sent", {})
    logger.info(
        "Monitor starting: symbols=%s poll=%ss telegram=%s alerts=%s",
        ",".join(settings.symbols), settings.poll_seconds,
        settings.telegram_enabled, settings.alerts_enabled,
    )
    if not settings.alerts_enabled:
        logger.warning("STRATEGY_ALERTS_ENABLED=false: monitoring data, but sending no setup alerts")

    while True:
        started = time.monotonic()
        for symbol in settings.symbols:
            try:
                data = {}
                for timeframe in ("1h", "15m", "5m", "1m"):
                    data[timeframe] = await api.candles(symbol, timeframe, settings.candle_count)
                # Candle timestamps are candle-open epochs. Require a recent completed
                # candle on every timeframe; stale/closed-market data must never alert.
                now = int(time.time())
                stale = []
                for timeframe, candles in data.items():
                    if len(candles) < 2:
                        stale.append(timeframe)
                        continue
                    last_completed = candles[-2]
                    age = now - (int(last_completed["epoch"]) + GRANULARITIES[timeframe])
                    if age > (3 * GRANULARITIES[timeframe] + 60) or age < -60:
                        stale.append(timeframe)
                if stale:
                    logger.warning("%s: stale/incomplete data on %s; skipping", symbol, ",".join(stale))
                    continue

                candidate = detect_candidate(
                    symbol, data["1h"], data["15m"], data["5m"], data["1m"]
                )
                if candidate is None:
                    logger.info("%s: no complete candidate", symbol)
                    continue
                key = f"{symbol}:{candidate.side}:{candidate.candle_epoch}"
                if key in state["sent"]:
                    logger.info("%s: duplicate candidate suppressed", symbol)
                    continue
                logger.warning("%s: candidate found; RR=1:%.1f", symbol, candidate.risk_reward)
                if settings.alerts_enabled and settings.telegram_enabled:
                    await send_telegram(
                        settings.telegram_bot_token,
                        settings.telegram_chat_id,
                        format_candidate(candidate),
                    )
                    state["sent"][key] = int(time.time())
                    # Keep state bounded.
                    if len(state["sent"]) > 1000:
                        state["sent"] = dict(list(state["sent"].items())[-700:])
                    save_state(settings.state_path, state)
                    logger.info("%s: Telegram alert sent", symbol)
                else:
                    logger.info("%s: candidate not sent because alerting is disabled", symbol)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("%s: monitoring cycle failed; will retry next cycle", symbol)
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(1, settings.poll_seconds - elapsed))


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Monitor stopped")
