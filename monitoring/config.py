"""Environment-backed configuration for the optional strategy monitor."""
from __future__ import annotations

import os
from dataclasses import dataclass

DEFAULT_SYMBOLS = (
    "frxXAUUSD",
    "frxEURUSD",
    "frxGBPUSD",
    "cryBTCUSD",
)


def _csv_env(name: str, default: tuple[str, ...]) -> tuple[str, ...]:
    raw = os.getenv(name, "").strip()
    return tuple(item.strip() for item in raw.split(",") if item.strip()) if raw else default


@dataclass(frozen=True)
class Settings:
    symbols: tuple[str, ...] = _csv_env("MONITOR_SYMBOLS", DEFAULT_SYMBOLS)
    poll_seconds: int = max(15, int(os.getenv("MONITOR_POLL_SECONDS", "60")))
    candle_count: int = min(500, max(60, int(os.getenv("MONITOR_CANDLE_COUNT", "120"))))
    telegram_bot_token: str = os.getenv("TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.getenv("TELEGRAM_CHAT_ID", "")
    telegram_enabled: bool = os.getenv("TELEGRAM_ENABLED", "false").lower() == "true"
    # Keep off until the strategy gates have been validated with replay/paper trading.
    alerts_enabled: bool = os.getenv("STRATEGY_ALERTS_ENABLED", "false").lower() == "true"
    state_path: str = os.getenv("MONITOR_STATE_PATH", "monitor_state.json")
    deriv_app_id: str = os.getenv("DERIV_APP_ID", "1089")
