# Deploy and Telegram setup

## 1. Telegram bot
1. In Telegram, open **@BotFather** → `/newbot` → copy the bot token.
2. Send any message (e.g. `/start`) to your new bot.
3. Locally: `export TELEGRAM_BOT_TOKEN=...` then `python -m monitoring.telegram_setup chat-id`.
4. `export TELEGRAM_CHAT_ID=...` then `python -m monitoring.telegram_setup test`.
5. Put the token and chat ID only in Render environment settings. Never commit them.

## 2. Render (pick one)
**A. Free:** in the existing `deriv-mcp` web service set `MONITOR_IN_PROCESS=true`.
Free web services sleep after 15 min without inbound traffic, so ping
`https://<service>.onrender.com/health` every ~10 min (UptimeRobot / cron-job.org).
No persistent disk: the dedupe file resets on restart (the engine only fires on the latest
1–2 completed 5M candles, so a restart can at worst repeat one very recent alert).

**B. Reliable ($7/mo):** add a Background Worker running `python monitor_worker.py`.

## 3. Staged enablement
1. `TELEGRAM_ENABLED=true`, `STRATEGY_ALERTS_ENABLED=false` → you get the startup message and
   heartbeat only; confirm Telegram works.
2. Paper-monitor with `STRATEGY_ALERTS_ENABLED=true` for several weeks; compare each alert to the chart.
3. Do not trade from alerts until the rulebook release gates are met.
