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

## 4. Keep the free Render instance awake (alerts only run while it is awake)
Render's free web service sleeps after ~15 minutes without inbound traffic, and a sleeping service scans nothing.
- **UptimeRobot (recommended, free):** New monitor -> HTTP(s) -> `https://deriv-mcp.onrender.com/health` -> every 5 minutes.
  `/health` always returns 200 and shows `monitor_last_cycle_age_s` (it should stay under ~120).
- **GitHub Actions (extra):** `.github/workflows/keepalive.yml` pings every 5 minutes. GitHub's scheduler can drift, so do not rely on it alone.
- **Always-on:** Render Starter plan ($7/mo) never sleeps. Cheapest guaranteed option.

## 5. Durable alert tracking (scorecard)
Every candidate is recorded and auto-scored from real 1M candles; send `/stats` to the bot.
On Render free the disk is wiped on restart, so use Supabase. Run once in the Supabase SQL editor:

```sql
create table if not exists strategy_alerts (
  id text primary key,
  symbol text, side text,
  entry double precision, stop double precision, target double precision, rr double precision,
  style text, alerted_at bigint, entry_epoch bigint,
  status text default 'open', closed_at bigint, r double precision
);
alter table strategy_alerts enable row level security;  -- the service key bypasses RLS; keep it server-side only
```
Then set `SUPABASE_URL` and `SUPABASE_SERVICE_KEY` in Render. Without them, tracking uses a local file.

## 6. R:R study (is 1:3 too strict?)
`/replay r25 400 study` shows win rate and net R per R:R bucket for setups that passed every candle rule.
Do not change MIN_RR from fewer than ~30 setups per bucket.
