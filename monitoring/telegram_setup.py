"""Telegram setup helper.

Usage (set TELEGRAM_BOT_TOKEN in your shell first; never commit it):
  python -m monitoring.telegram_setup chat-id   # after sending any message to your bot
  python -m monitoring.telegram_setup test      # needs TELEGRAM_CHAT_ID too
"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import urllib.request

from .telegram import send_telegram


def find_chat_ids(token: str) -> list[tuple[str, str]]:
    with urllib.request.urlopen(f"https://api.telegram.org/bot{token}/getUpdates", timeout=15) as r:
        data = json.loads(r.read().decode())
    seen: dict[str, str] = {}
    for update in data.get("result", []):
        chat = (update.get("message") or update.get("channel_post") or {}).get("chat") or {}
        if "id" in chat:
            seen[str(chat["id"])] = chat.get("title") or chat.get("username") or chat.get("first_name") or ""
    return list(seen.items())


def main() -> int:
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if not token:
        print("Set TELEGRAM_BOT_TOKEN first.")
        return 1
    if cmd == "chat-id":
        ids = find_chat_ids(token)
        if not ids:
            print("No chats found. Send any message (e.g. /start) to your bot, then run again.")
            return 1
        for chat_id, name in ids:
            print(f"chat_id={chat_id}  ({name})")
        return 0
    if cmd == "test":
        chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
        asyncio.run(send_telegram(token, chat_id, "✅ Test message from the candle-behaviour monitor."))
        print("Sent. Check Telegram.")
        return 0
    print(__doc__)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
