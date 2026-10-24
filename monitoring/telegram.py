"""Telegram notifications using the Bot API."""
from __future__ import annotations

import asyncio
import json
import logging
import urllib.parse
import urllib.request

from .strategy import Candidate

logger = logging.getLogger(__name__)


def format_candidate(candidate: Candidate) -> str:
    direction = "🟢 BUY" if candidate.side == "BUY" else "🔴 SELL"
    return (
        f"📊 STRATEGY SETUP CANDIDATE\n"
        f"{candidate.symbol} · {direction}\n\n"
        f"Entry: {candidate.entry:.5f}\n"
        f"Stop-loss: {candidate.stop_loss:.5f}\n"
        f"Take-profit (3R): {candidate.take_profit:.5f}\n"
        f"Planned R:R: 1:{candidate.risk_reward:.0f}\n\n"
        f"Why it triggered:\n{candidate.explanation}\n\n"
        f"Invalidation: {candidate.invalidation}\n\n"
        f"Research/paper-monitoring only. Not financial advice; verify price and execution."
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
