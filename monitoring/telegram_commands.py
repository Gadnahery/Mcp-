"""Telegram command handler for on-demand status and pair results."""
from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.parse
import urllib.request
from typing import Any, Callable

logger = logging.getLogger("telegram-commands")

# Friendly names → Deriv symbol codes
SYMBOL_ALIASES: dict[str, str] = {
    "xau": "frxXAUUSD",
    "gold": "frxXAUUSD",
    "xauusd": "frxXAUUSD",
    "eur": "frxEURUSD",
    "eurusd": "frxEURUSD",
    "gbp": "frxGBPUSD",
    "gbpusd": "frxGBPUSD",
    "btc": "cryBTCUSD",
    "btcusd": "cryBTCUSD",
    "bitcoin": "cryBTCUSD",
    "frxxauusd": "frxXAUUSD",
    "frxeurusd": "frxEURUSD",
    "frxgbpusd": "frxGBPUSD",
    "crybtcusd": "cryBTCUSD",
    # Volatility indices
    "v75": "R_75",
    "vol75": "R_75",
    "volatility75": "R_75",
    "r75": "R_75",
    "r_75": "R_75",
    "v25": "R_25",
    "vol25": "R_25",
    "volatility25": "R_25",
    "r25": "R_25",
    "r_25": "R_25",
}

HELP_TEXT = """🤖 Deriv Strategy Bot

Commands:
/status — overall monitor status
/pair SYMBOL — latest live result for one pair
  e.g. /pair gold  /pair btc  /pair v75  /pair v25
/replay SYMBOL — historical replay (was there a setup?)
  e.g. /replay btc  /replay v75  /replay v25
  Optional count: /replay btc 200  (5M candles, 80-400)
  Variants: nearest nopb nospread rr2  (e.g. /replay btc 400 nearest rr2)
  Study: /replay r25 400 study  (win rate by R:R bucket)
/candidates — recent live trade candidates
/stats — alert scorecard (wins, stops, net R, auto-scored)
/symbols — list monitored symbols
/help — this message

Shortcuts: /gold /eur /gbp /btc /v75 /v25
"""


def resolve_symbol(raw: str) -> str | None:
    key = raw.strip().lower().replace("/", "").replace("-", "").replace("_", "")
    if key in SYMBOL_ALIASES:
        return SYMBOL_ALIASES[key]
    # allow full Deriv codes
    if key.startswith("frx") or key.startswith("cry") or key.startswith("r_"):
        return raw.strip()
    return SYMBOL_ALIASES.get(key)


def _fmt_age(epoch: int | None) -> str:
    if not epoch:
        return "n/a"
    age = max(0, int(time.time()) - int(epoch))
    if age < 60:
        return f"{age}s ago"
    if age < 3600:
        return f"{age // 60}m ago"
    return f"{age // 3600}h ago"


def format_status(status: dict[str, Any]) -> str:
    running = "🟢 running" if status.get("running") or status.get("started_at") else "🔴 stopped"
    lines = [
        "📡 Monitor status",
        f"State: {running}",
        f"Cycles: {status.get('cycles', 0)}",
        f"Last cycle: {_fmt_age(status.get('last_cycle_at'))}",
        f"Alerts: {'ON' if status.get('alerts_enabled') else 'OFF'}",
        f"Telegram: {'ON' if status.get('telegram_enabled') else 'OFF'}",
        "",
        "Symbols:",
    ]
    symbols = status.get("symbols") or {}
    if not symbols:
        lines.append("  (none yet — waiting for first cycle)")
    for sym, info in symbols.items():
        data = info.get("data", "?")
        if data != "ok":
            lines.append(f"• {sym}: {data} ({_fmt_age(info.get('checked_at'))})")
            continue
        status_txt = info.get("status", "?")
        side = info.get("side") or ""
        stage = info.get("stage") or ""
        why = (info.get("why_not") or [""])[0]
        lines.append(f"• {sym}: {status_txt} {side} · {stage}")
        if why:
            lines.append(f"  → {why[:120]}")
    candidates = status.get("candidates") or []
    if candidates:
        lines.append(f"\nRecent candidates: {len(candidates)}")
    return "\n".join(lines)


def format_pair(symbol: str, status: dict[str, Any]) -> str:
    info = (status.get("symbols") or {}).get(symbol)
    if not info:
        monitored = ", ".join((status.get("symbols") or {}).keys()) or "none"
        return (
            f"No data yet for {symbol}.\n"
            f"Monitored: {monitored}\n"
            f"Try /status or wait one poll cycle."
        )
    data = info.get("data", "?")
    lines = [f"📈 {symbol}", f"Checked: {_fmt_age(info.get('checked_at'))}"]
    if data != "ok":
        lines.append(f"Data: {data}")
        if data == "stale_or_market_closed":
            lines.append("(Market may be closed — e.g. weekend forex)")
        return "\n".join(lines)

    lines.append(f"Verdict: {info.get('status', '?')} {info.get('side') or ''}".rstrip())
    lines.append(f"Stage: {info.get('stage') or 'n/a'}")
    for why in (info.get("why_not") or [])[:3]:
        lines.append(f"Why not: {why}")
    evidence = info.get("evidence") or []
    if evidence:
        lines.append("Evidence:")
        for e in evidence[-3:]:
            lines.append(f"• {e}")
    # attach matching candidates for this symbol
    for c in reversed(status.get("candidates") or []):
        if c.get("symbol") == symbol:
            lines.append(
                f"\nLast candidate: {c.get('side')} entry={c.get('entry')} "
                f"SL={c.get('stop')} TP={c.get('target')} RR=1:{c.get('rr')}"
            )
            break
    return "\n".join(lines)


def format_candidates(status: dict[str, Any]) -> str:
    items = status.get("candidates") or []
    if not items:
        return "No trade candidates stored yet."
    lines = [f"🎯 Recent candidates ({len(items)})"]
    for c in reversed(items[-10:]):
        lines.append(
            f"• {c.get('symbol')} {c.get('side')} "
            f"entry={c.get('entry')} SL={c.get('stop')} TP={c.get('target')} "
            f"RR=1:{c.get('rr')} ({_fmt_age(c.get('found_at'))})"
        )
    return "\n".join(lines)


async def send_message(bot_token: str, chat_id: str, text: str) -> None:
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    body = urllib.parse.urlencode(
        {"chat_id": chat_id, "text": text[:4000]}
    ).encode()
    request = urllib.request.Request(url, data=body, method="POST")

    def _send() -> None:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError(f"Telegram send failed: {payload}")

    await asyncio.to_thread(_send)


async def get_updates(bot_token: str, offset: int | None) -> list[dict]:
    params: dict[str, Any] = {"timeout": 25}
    if offset is not None:
        params["offset"] = offset
    query = urllib.parse.urlencode(params)
    url = f"https://api.telegram.org/bot{bot_token}/getUpdates?{query}"

    def _get() -> list[dict]:
        with urllib.request.urlopen(url, timeout=35) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            return []
        return payload.get("result") or []

    return await asyncio.to_thread(_get)


def handle_command(
    text: str,
    status_provider: Callable[[], dict[str, Any]],
) -> str:
    raw = (text or "").strip()
    if not raw:
        return HELP_TEXT.replace("*", "")
    parts = raw.split()
    cmd = parts[0].lower().split("@")[0]  # strip @botname
    arg = parts[1] if len(parts) > 1 else ""

    status = status_provider()

    if cmd in ("/start", "/help"):
        return HELP_TEXT.replace("*", "")
    if cmd == "/status":
        return format_status(status)
    if cmd == "/stats":
        from .ledger import format_stats
        return format_stats(status.get("ledger"))

    if cmd == "/candidates":
        return format_candidates(status)
    if cmd == "/symbols":
        syms = list((status.get("symbols") or {}).keys()) or list(
            SYMBOL_ALIASES[k] for k in ("gold", "eur", "gbp", "btc")
        )
        # unique preserve order
        seen = set()
        ordered = []
        for s in syms:
            if s not in seen:
                seen.add(s)
                ordered.append(s)
        return "Monitored symbols:\n" + "\n".join(f"• {s}" for s in ordered)
    if cmd == "/pair":
        if not arg:
            return "Usage: /pair gold | /pair eur | /pair gbp | /pair btc"
        symbol = resolve_symbol(arg)
        if not symbol:
            return f"Unknown symbol '{arg}'. Try: gold, eur, gbp, btc"
        return format_pair(symbol, status)
    # shortcuts
    if cmd in ("/gold", "/xau", "/xauusd"):
        return format_pair("frxXAUUSD", status)
    if cmd in ("/eur", "/eurusd"):
        return format_pair("frxEURUSD", status)
    if cmd in ("/gbp", "/gbpusd"):
        return format_pair("frxGBPUSD", status)
    if cmd in ("/btc", "/btcusd", "/bitcoin"):
        return format_pair("cryBTCUSD", status)
    if cmd in ("/v75", "/vol75", "/r75", "/r_75"):
        return format_pair("R_75", status)
    if cmd in ("/v25", "/vol25", "/r25", "/r_25"):
        return format_pair("R_25", status)
    if cmd == "/replay":
        # Handled asynchronously in command_loop (needs market data).
        return "__REPLAY__"

    return "Unknown command. Send /help for the list."


async def run_replay_command(text: str) -> str:
    """Fetch candles from Deriv and run strategy replay for a symbol."""
    parts = (text or "").split()
    if len(parts) < 2:
        return (
            "Usage: /replay SYMBOL [candle_count]\n"
            "Examples:\n"
            "  /replay btc\n"
            "  /replay gold 200\n"
            "  /replay eur 150"
        )
    symbol = resolve_symbol(parts[1])
    if not symbol:
        return f"Unknown symbol '{parts[1]}'. Try: gold, eur, gbp, btc"

    count = 180
    study = False
    opts: dict[str, Any] = {}
    for tok in parts[2:]:
        t = tok.lower()
        if t.isdigit():
            count = int(t)
        elif t == "nearest":
            opts["target_mode"] = "nearest"
        elif t in ("nopb", "nopullback"):
            opts["pullback"] = False
        elif t == "nospread":
            opts["spread"] = 0.0
        elif t == "study":
            study = True
        elif t.startswith("rr") and t[2:].replace(".", "", 1).isdigit():
            opts["min_rr"] = float(t[2:])
        else:
            return "Options: <count 80-400> study nearest nopb nospread rr2 (e.g. /replay btc 400 study)"
    count = max(80, min(400, count))

    try:
        from .market_data import DerivMarketData
        from .replay_engine import format_replay_report, run_replay

        api = DerivMarketData()
        m15 = await api.candles(symbol, "15m", min(500, count // 3 + 60))
        m5 = await api.candles(symbol, "5m", count)
        try:
            # 1M must cover the whole 5M window (5 x the 5M count), otherwise early bars cannot be judged
            m1 = await api.candles(symbol, "1m", min(2500, count * 5 + 30))
        except Exception:
            m1 = []
        warmup = min(60, max(20, len(m5) // 4))
        if study:
            from .replay_engine import format_rr_study, rr_study
            result = run_replay(symbol, m15, m5, m1=None, warmup=warmup, opts={**opts, "min_rr": 0.01, "pullback": False})
            return format_rr_study(symbol, rr_study(result.get("candidates") or []), result.get("bars_evaluated", 0))
        result = run_replay(symbol, m15, m5, m1=None, warmup=warmup, opts=opts)
        return format_replay_report(result)
    except Exception as exc:
        logger.exception("Replay failed for %s", symbol)
        return f"Replay failed for {symbol}: {exc}"


async def _delete_webhook(bot_token: str) -> None:
    """Ensure long-polling works (webhook and polling cannot run together)."""
    url = f"https://api.telegram.org/bot{bot_token}/deleteWebhook?drop_pending_updates=false"

    def _call() -> None:
        with urllib.request.urlopen(url, timeout=15) as response:
            json.loads(response.read().decode("utf-8"))

    try:
        await asyncio.to_thread(_call)
        logger.info("Telegram webhook cleared for long-polling")
    except Exception:
        logger.exception("deleteWebhook failed (continuing)")


async def command_loop(
    bot_token: str,
    allowed_chat_id: str,
    status_provider: Callable[[], dict[str, Any]],
) -> None:
    """Long-poll Telegram for commands from the allowed chat only."""
    await _delete_webhook(bot_token)
    offset: int | None = None
    logger.info("Telegram command listener started (chat_id=%s)", allowed_chat_id)
    try:
        await send_message(
            bot_token,
            allowed_chat_id,
            "🟢 Bot online again.\nSend /status /btc /v75 /v25 /replay btc",
        )
    except Exception:
        logger.exception("Startup ping failed")

    while True:
        try:
            updates = await get_updates(bot_token, offset)
            for upd in updates:
                offset = int(upd["update_id"]) + 1
                msg = upd.get("message") or upd.get("edited_message") or {}
                chat = msg.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                text = msg.get("text") or ""
                if not text.startswith("/"):
                    continue
                if allowed_chat_id and chat_id != str(allowed_chat_id):
                    logger.warning("Ignoring command from unauthorized chat %s", chat_id)
                    continue
                cmd0 = text.split()[0].lower().split("@")[0] if text else ""
                logger.info("Command from %s: %s", chat_id, text[:80])
                try:
                    if cmd0 == "/replay":
                        await send_message(bot_token, chat_id, "⏳ Running replay…")
                        reply = await run_replay_command(text)
                    else:
                        reply = handle_command(text, status_provider)
                    await send_message(bot_token, chat_id, reply)
                except Exception:
                    logger.exception("Failed to reply to command: %s", text[:80])
                    try:
                        await send_message(bot_token, chat_id, "Error handling that command. Try again.")
                    except Exception:
                        pass
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Telegram poll error: %s; retrying in 5s", exc)
            await asyncio.sleep(5)
