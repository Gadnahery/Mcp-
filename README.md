# Deriv MCP Server

Gives Claude, Cursor, ChatGPT and other AI assistants access to Deriv market data (forex, synthetic indices, gold, and other supported markets).

## Existing MCP tools

| Tool | Description |
|---|---|
| `get_active_symbols` | List active Deriv symbols |
| `get_ticks` | Retrieve recent ticks |
| `get_ticks_history` | Retrieve historical ticks or OHLC candles |
| `get_account_balance` | Read account balance where the configured endpoint/token supports it |
| `get_symbol_info` | Retrieve information about one symbol |

## Local setup

```bash
python -m venv .venv
# Windows: .venv\\Scripts\\activate
# macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

For an authenticated Deriv feature, set `DERIV_API_TOKEN` in your environment. Do not commit real tokens. If a token was ever committed to Git history, revoke it and create a replacement; deleting it from the latest file does not remove it from history.

## Optional strategy monitor (first implementation)

The monitor is an independent process so it does not change the existing MCP transport or routes. It retrieves candles for the configured instruments on 15M and 5M, evaluates a conservative rule-based candidate detector, suppresses repeated alerts, and can send a Telegram message. The 1H and 1M timeframes are not required by the strategy engine.

**Important:** this is an experimental candidate detector based on a mechanical approximation of the candle-behaviour study. It is not yet a complete encoding of the study notes and has not been proven profitable. Run historical replay and paper monitoring before enabling live notifications. It never places orders.

### Configure

Copy the relevant values from `.env.monitor.example` into the environment of the monitor service:

- `MONITOR_SYMBOLS`: comma-separated Deriv symbol codes. Check each code with `get_active_symbols`; symbols can differ by account/market.
- `MONITOR_POLL_SECONDS`: minimum delay between monitoring cycles (default 60).
- `MONITOR_CANDLE_COUNT`: candles requested per timeframe (60–500).
- `TELEGRAM_ENABLED`: set to `true` only after setting the bot token and chat ID.
- `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`: keep these as Render environment secrets; never put them in source control.
- `STRATEGY_ALERTS_ENABLED`: defaults to `false`. Leave disabled during setup and testing.
- `MONITOR_STATE_PATH`: path for duplicate-alert state. A persistent disk is needed if state must survive service restarts.

Create a Telegram bot using Telegram's official BotFather, send it a message, then configure the bot token and destination chat ID in the Render environment. Do not share the token publicly.

### Run locally

```bash
python monitor_worker.py
```

With default settings it monitors and logs candidates but sends no alerts. To test delivery, set `TELEGRAM_ENABLED=true` and `STRATEGY_ALERTS_ENABLED=true` only after configuring the Telegram credentials and reviewing the detector. The monitor logs a candidate's reasoning and proposed entry/stop/target; prices should be checked against the live chart before any decision.

### Deploy on Render

Keep the existing Render web service running the MCP server. Create a **separate service** from this same repository for monitoring and set its start command to:

```bash
python monitor_worker.py
```

Use the same branch/revision for both services. A continuously running worker may require a paid Render service depending on current Render plan limits; confirm pricing before creating it. Configure the environment variables in the Render dashboard, not in Git. The existing `render.yaml` remains for the MCP web service.

### Strategy and safety limits

- Higher-timeframe context uses close-to-close progress (not candle colour alone).
- The engine uses 15M context and 5M execution: data quality, 15M close-to-close dominance, 5M approach/conflict, detected 15M swing references, a 5M sweep/reclaim at a reference, the post-sweep struggle/base on 5M, a decisive 5M close beyond the local range, a structural invalidation stop, and the next detected reaction reference. See [Strategy Engine Rulebook](docs/STRATEGY_ENGINE_RULEBOOK.md) for the full rules, provisional assumptions, test plan and release gates.
- The target must be the next detected higher-timeframe swing in the trade direction and must leave at least 1:3 planned R:R; otherwise the engine returns NO_TRADE.
- Telegram messages include the evidence recorded at each stage, not only BUY/SELL and prices.
- The automatic swing-point, reaction-zone tolerance and possible-base detectors are **provisional coding proxies**. The study notes do not yet specify exact universal thresholds for those concepts, so they must be reviewed against the annotated examples before being treated as confirmed rules.
- Entry-at-decisive-close is the only automated entry style currently emitted. The notes say immediate entry versus pullback is context-dependent; that comparison is not yet fully codified, so alerts must remain disabled until chart replay verifies it.
- A missing, stale, contradictory, or incomplete setup should produce no alert.
- A rule-based detector is not a trained AI model. AI-based interpretation should be added only as an explanatory layer after the confirmed rules and historical test cases are documented.

## Symbol examples

| Symbol | Meaning |
|---|---|
| `frxEURUSD` | EUR/USD |
| `frxGBPUSD` | GBP/USD |
| `frxXAUUSD` | Gold |
| `R_100` | Volatility 100 Index |
| `1HZ100V` | Volatility 100 (1s) |

Always verify current symbol availability before monitoring.

## Security

The server reads `DERIV_API_TOKEN` from the environment. Never hardcode Deriv credentials, Telegram bot tokens, or chat IDs in source files. If a credential was previously committed, rotate/revoke it.
