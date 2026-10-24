"""Telegram notifications using the Bot API."""
from __future__ import annotations

import asyncio
import json
import urllib.parse
import urllib.request

from .strategy import Candidate


def format_candidate(candidate: Candidate) -> str:
    direction = "🟢 BUY" if candidate.side == "BUY" else "🔴 SELL"
    evidence = "\n".join(f"• {item}" for item in candidate.evidence) or candidate.explanation
    return (
        f"📊 CANDLE-BEHAVIOUR SETUP CANDIDATE\n"
        f"{candidate.symbol} · {direction}\n"
        f"Entry style: {candidate.entry_style.replace('_', ' ')}\n\n"
        f"Entry: {candidate.entry:.5f}\n"
        f"Stop-loss: {candidate.stop_loss:.5f}\n"
        f"Take-profit: {candidate.take_profit:.5f}\n"
        f"Planned R:R: 1:{candidate.risk_reward:.2f}\n"
        f"Target reference: {candidate.target_reference}\n\n"
        f"Evidence by stage:\n{evidence}\n\n"
        f"Invalidation: {candidate.invalidation}\n\n"
        "IMPORTANT: Experimental rule-based candidate, not a validated strategy signal. "
        "Verify the chart, reaction area, spread and execution before making any decision."
    )


async def send_telegram(bot_token: str, chat_id: str, message: str) -> None:
    if not bot_token or not chat_id:
        raise RuntimeError("Telegram requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID")
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": message}).encode()
    request = urllib.request.Request(url, data=body, method="POST")

    def _send() -> None:
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if not payload.get("ok"):
            raise RuntimeError("Telegram API did not confirm message delivery")

    await asyncio.to_thread(_send)
