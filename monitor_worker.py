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
from monitoring.strategy import analyze_setup
from monitoring.telegram import format_candidate, send_telegram
from monitoring.telegram_commands import command_loop

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger("strategy-monitor")


# Live status shared with server.py (/status route and monitor_status MCP tool).
STATUS: dict[str, Any] = {
    "started_at": None, "last_cycle_at": None, "cycles": 0,
    "alerts_enabled": False, "telegram_enabled": False,
    "stage_tally": {}, "symbols": {}, "candidates": [],
}


def record_analysis(symbol: str, analysis: Any, now: int | None = None) -> None:
    """Remember the latest verdict per symbol, a tally of where evaluations stop, and candidates."""
    now = now or int(time.time())
    stage = "CANDIDATE" if analysis.candidate else analysis.stage
    STATUS["stage_tally"][stage] = STATUS["stage_tally"].get(stage, 0) + 1
    STATUS["symbols"][symbol] = {
        "checked_at": now, "data": "ok", "status": analysis.status, "side": analysis.side,
        "stage": analysis.stage, "why_not": list(analysis.missing)[:2],
        "evidence": list(analysis.evidence)[-3:],
    }
    if analysis.candidate and not any(
        x["symbol"] == symbol and x["confirm_epoch"] == analysis.candidate.candle_epoch
        for x in STATUS["candidates"]
    ):
        c = analysis.candidate
        STATUS["candidates"] = (STATUS["candidates"] + [{
            "found_at": now, "symbol": symbol, "side": c.side, "entry": c.entry,
            "stop": c.stop_loss, "target": c.take_profit, "rr": round(c.risk_reward, 2),
            "confirm_epoch": c.candle_epoch,
        }])[-20:]


def record_data_state(symbol: str, state: str) -> None:
    STATUS["symbols"][symbol] = {"checked_at": int(time.time()), "data": state}


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

    STATUS.update(started_at=int(time.time()), alerts_enabled=settings.alerts_enabled,
                  telegram_enabled=settings.telegram_enabled)
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

    async def notify(text: str) -> None:
        if settings.telegram_enabled:
            try:
                await send_telegram(settings.telegram_bot_token, settings.telegram_chat_id, text)
            except Exception:
                logger.exception("Telegram status message failed")

    heartbeat_hours = float(os.getenv("HEARTBEAT_HOURS", "24"))
    stats = {"cycles": 0, "scanned": 0, "stale": 0, "errors": 0, "candidates": 0}
    last_heartbeat = time.monotonic()

    # Interactive Telegram commands: prefer webhook (TELEGRAM_USE_WEBHOOK=true).
    # Long-polling fights with free-tier sleep; webhook wakes the app on each message.
    cmd_task = None
    use_webhook = os.getenv("TELEGRAM_USE_WEBHOOK", "true").lower() == "true"
    if settings.telegram_enabled and settings.telegram_bot_token and settings.telegram_chat_id:
        if use_webhook:
            logger.info("Telegram commands via webhook (long-poll disabled)")
        else:
            def _status() -> dict[str, Any]:
                out = dict(STATUS)
                out["running"] = out.get("started_at") is not None
                return out

            cmd_task = asyncio.create_task(
                command_loop(settings.telegram_bot_token, settings.telegram_chat_id, _status)
            )
            logger.info("Telegram command bot enabled (long-poll)")

    await notify(
        "✅ Candle-behaviour monitor online\n"
        f"Symbols: {', '.join(settings.symbols)}\n"
        f"Setup alerts: {'ON' if settings.alerts_enabled else 'OFF (test mode)'}\n"
        "Commands: /status /pair gold /gold /eur /gbp /btc /candidates /help\n"
        "Research-only; places no orders."
    )

    while True:
        started = time.monotonic()
        for symbol in settings.symbols:
            try:
                data = {}
                for timeframe in ("15m", "5m"):
                    data[timeframe] = await api.candles(symbol, timeframe, settings.candle_count)
                # 1M: more bars for micro retest / tighter limit entry (R:R recovery)
                try:
                    data["1m"] = await api.candles(symbol, "1m", min(300, max(120, settings.candle_count * 2)))
                except Exception:
                    data["1m"] = []
                    logger.warning("%s: 1m candles unavailable; continuing with 15m/5m only", symbol)
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
                    stats["stale"] += 1
                    record_data_state(symbol, "stale_or_market_closed")
                    continue
                stats["scanned"] += 1

                analysis = analyze_setup(symbol, data["15m"], data["5m"], data.get("1m") or None, None)
                record_analysis(symbol, analysis)
                candidate = analysis.candidate
                if candidate is None:
                    logger.info("%s: no complete candidate", symbol)
                    continue
                key = f"{symbol}:{candidate.side}:{candidate.candle_epoch}"
                if key in state["sent"]:
                    logger.info("%s: duplicate candidate suppressed", symbol)
                    continue
                stats["candidates"] += 1
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
                stats["errors"] += 1
                record_data_state(symbol, "error")
                logger.exception("%s: monitoring cycle failed; will retry next cycle", symbol)
        stats["cycles"] += 1
        STATUS["cycles"] += 1
        STATUS["last_cycle_at"] = int(time.time())
        if heartbeat_hours > 0 and time.monotonic() - last_heartbeat >= heartbeat_hours * 3600:
            await notify(
                f"💓 Monitor alive — {stats['cycles']} cycles, {stats['scanned']} symbol scans, "
                f"{stats['stale']} skipped (closed/stale), {stats['errors']} errors, "
                f"{stats['candidates']} candidates since last heartbeat."
            )
            stats.update(cycles=0, scanned=0, stale=0, errors=0, candidates=0)
            last_heartbeat = time.monotonic()
        elapsed = time.monotonic() - started
        await asyncio.sleep(max(1, settings.poll_seconds - elapsed))


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("Monitor stopped")
