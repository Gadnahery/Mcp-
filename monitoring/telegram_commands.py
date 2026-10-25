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
}

HELP_TEXT = """🤖 *Deriv Strategy Bot*

Commands:
/status — overall monitor status
/pair SYMBOL — latest result for one pair
  e.g. /pair gold  /pair eur  /pair btc
/candidates — recent trade candidates
/symbols — list monitored symbols
/help — this message

Shortcuts: /gold /eur /gbp /btc
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

    return "Unknown command. Send /help for the list."


async def command_loop(
    bot_token: str,
    allowed_chat_id: str,
    status_provider: Callable[[], dict[str, Any]],
) -> None:
    """Long-poll Telegram for commands from the allowed chat only."""
    offset: int | None = None
    logger.info("Telegram command listener started (chat_id=%s)", allowed_chat_id)
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
                reply = handle_command(text, status_provider)
                try:
                    await send_message(bot_token, chat_id, reply)
                except Exception:
                    logger.exception("Failed to reply to command")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Telegram command poll failed; retrying in 5s")
            await asyncio.sleep(5)
