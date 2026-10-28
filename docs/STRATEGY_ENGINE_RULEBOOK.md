# Candle-Behaviour Strategy Engine — Rulebook & Validation Plan

**Status:** research implementation; not approved for live trading  
**Engine:** Deriv MCP strategy monitor  
**Timeframes:** 15-minute structure/context + 5-minute sweep/control and execution; 1-minute candles resolve shadow-trade outcomes, not entries  
**Execution:** alerts only; no order placement

## 1. Purpose and operating principle

The engine is intended to turn the candle-behaviour study into a repeatable candidate filter. It should prefer **NO_TRADE** over a weak, ambiguous, stale, or incomplete setup. A candidate is not a promise of profitability or a recommendation to place a trade.

The strategy's working ideas are:
- Location/context comes before an entry.
- Dominance is measured by close-to-close progress, not candle colour alone.
- A liquidity sweep is context, never an entry by itself.
- After a sweep, observe rejection/indecision and the response that shows control.
- Place invalidation beyond the price that disproves the idea.
- Require at least **1:3 planned reward-to-risk** to the next plausible reaction area.

## 2. Timeframe roles

| Timeframe | Role | Engine use |
|---|---|---|
| 15M | Context, meaningful swing references, reaction areas | Detect provisional swing highs/lows, structural progression and close-to-close dominance fallback |
| 5M | Approach, sweep/reclaim, post-sweep response, confirmation and entry | Evaluate the sequence and calculate entry, stop, target and planned R:R |

The 1H timeframe is intentionally not used in the current replay configuration. The 1M execution layer is currently disabled; entries use the completed 5M confirmation close. This must be kept explicit in replay output and documentation.

## 3. Setup sequence

### Gate A — Data quality
- Require at least 20 valid candles on both timeframes.
- Candle OHLC must be finite and internally consistent: low ≤ open/close ≤ high.
- Sort by epoch and collapse duplicate timestamps.
- Exclude the newest candle from signal logic because it may still be forming.
- The monitor separately rejects stale or implausibly future completed candles.
- If data is missing or unusable, return **NO_TRADE**.

### Gate B — 15M context and reference levels
- First infer provisional structure from the latest two confirmed swing highs and lows: both higher means bullish structure; both lower means bearish structure; disagreement is mixed.
- Also measure three consecutive close-to-close advances or declines. This is a short-term progress observation, not a substitute for swing structure.
- If structure is unclear, use close-to-close progress as fallback context; if both are unclear, context remains mixed.
- Detect local swing highs/lows using a two-candle wing on either side. This is a **provisional coding proxy**, not a fully specified user-confirmed swing rule.
- Reaction-area tolerance is currently 15% of the median range of the last 20 completed 15M candles. This threshold is provisional and requires annotated-chart validation.

### Gate C — 5M approach/conflict
- Record 5M close-to-close dominance when present.
- Record when 5M progress conflicts with the 15M structural context, but do not automatically reject the setup before examining its sweep and post-sweep response.
- Unclear 15M context must not be treated as an opposing direction.
- A counter-bias setup must pass the stricter three-candle confirmation gate; an unambiguous continuation may use the normal confirmation gate.

### Gate D — Sweep and reclaim
- BUY candidate context: price trades below a detected 15M swing low and the same 5M candle closes back above that reference.
- SELL candidate context: price trades above a detected 15M swing high and the same 5M candle closes back below that reference.
- The current detector searches only a recent subset of the 5M candles for a qualifying sweep.
- A sweep alone never produces a candidate.

### Gate E — Post-sweep reaction and control confirmation
- Require enough completed 5M candles after the sweep to assess the response.
- A sweep alone, a zone touch, or a wick is not an entry.
- With no clear opposing 15M bias, two consecutive completed 5M directional-body closes with close-to-close progress may confirm control; a third matching close is stronger.
- **Counter-bias gate:** when a SELL opposes bullish 15M structural/close-progress context or a BUY opposes bearish context, require three consecutive directional 5M closes with close-to-close progress, no body/range below 0.20, average body/range of at least 0.45, and the final close beyond the sweep candle's opposite boundary (SELL below its low; BUY above its high). If any condition fails, return **NO_TRADE**.
- The engine scans for a qualifying three-candle sequence rather than accepting an earlier weak pair and ignoring a later stronger sequence.
- These body-strength thresholds are provisional research settings and must be reviewed against annotated historical replay.
- Signal entry reference remains the final 5M confirmation close; replay and the shadow ledger use the first post-signal 1M candle open as an executable-fill estimate when available. Live execution is not enabled.
- Only a confirmation on the latest completed 5M candle is eligible; any older confirmation is rejected as stale before it can be presented as an executable entry. Pullback entry is disabled by default.

### Gate F — Invalidation, target and reward-to-risk
- BUY stop: the swept low, extended to any lower low made before confirmation.
- SELL stop: the swept high, extended to any higher high made before confirmation.
- Targets are selected from significant reaction/liquidity areas on both 5M and 15M, nearest eligible area first in the trade direction.
- Risk and reward must both be positive.
- Planned reward-to-risk must be at least 3.0 after the configured assumed spread; otherwise return **NO_TRADE**.
- If a symbol has no explicit spread assumption, return **NO_TRADE** at the cost-model gate. Never silently substitute zero spread for an unknown symbol.
- The spread defaults are provisional for only the configured symbols. Populate and periodically check ASSUMED_SPREADS for each symbol from actual trading conditions; assumed spread does not account for all slippage, execution delay or market impact.
- If no valid target reference is found, do not invent one; return **NO_TRADE**.

## 4. Candidate alert contents

A candidate should state:
- Symbol and side (BUY/SELL)
- Confirmation candle timestamp
- Proposed entry, stop loss and target
- Planned reward-to-risk
- Evidence for context, sweep/reclaim, reaction, confirmation and risk gate
- Invalidation condition
- A clear note that the output is a research candidate, not an executed order

## 5. Monitor and delivery safety

- The monitor is a separate process; the existing MCP server remains the web service.
- Telegram and strategy alerts default to disabled.
- Enable delivery only after historical replay, paper monitoring and credential checks.
- Keep API keys, Telegram bot tokens and chat IDs in Render environment secrets, never in code or commits.
- Duplicate suppression uses a local state file. A persistent disk or external durable store is needed if deduplication must survive worker restarts/redeploys.
- The worker logs candidate/error details and retries on later cycles. Repeated service errors must be reviewed in logs.
- The monitor must not place trades or request trade permissions.

## 6. Known limitations and risks

1. **Not fully validated:** current tests are basic unit tests, not a broad, realistic backtest.
2. **Heuristic structure:** swing points, reaction tolerance and base detection are proxies; they can miss meaningful human-marked areas or label irrelevant ones.
3. **Potential sequence bias:** the detector chooses a recent qualifying sweep and uses a fixed reaction-window heuristic. It needs systematic candle-by-candle replay against annotated examples.
4. **Execution assumptions:** the alert's entry is the confirming 5M close, but replay/ledger estimate a fill at the first subsequent 1M open when available. Fixed assumed spread is included in planned R:R and replay target R; variable spread, commissions, slippage and latency remain unmodelled.
5. **Market/session differences:** FX, gold, crypto and synthetic indices do not share identical session or candle behaviour. Validate per instrument family before enabling it.
6. **Sparse evidence:** a single screenshot or one historical example cannot establish an edge.
7. **No automatic position sizing or daily risk controls:** this component only proposes a candidate. It does not calculate safe stake size or enforce a portfolio loss limit.

## 7. Required validation plan

### Stage 1 — Unit and safety tests
- Missing/short data returns NO_TRADE.
- Malformed, non-finite, duplicate and unordered candles cannot create false signals.
- The last forming candle is excluded.
- A sweep without later confirmation never creates a candidate.
- An unclear 15M direction does not falsely reject a 5M move as opposed.
- A clear, continuing 5M move against a clearly dominant 15M context is rejected.
- Stops and targets are on the correct side of entry; risk/reward are positive.
- Any setup below 1:3 is rejected.
- Stale data, API errors and Telegram errors do not crash the worker permanently or create repeated duplicate alerts.

### Stage 2 — Historical replay
- Use exact OHLC candles for both 15M and 5M; screenshots alone are insufficient to validate timing.
- Record each gate, evidence, rejected reason, entry, stop, target, planned and realized R:R.
- Include winning, losing, missed, ambiguous and no-trade examples.
- Freeze the rules before measuring the final holdout period.
- Avoid tuning repeatedly against the same Friday example; keep unseen data for out-of-sample review.

### Stage 3 — Paper monitoring
- Run with real-time data and no orders for multiple weeks and different market conditions.
- Compare every alert to the chart and record false positives, missed setups, stale-feed skips and delivery failures.
- Include realistic spread/slippage and delayed entry in the evaluation.
- Review results separately for each instrument family.

### Stage 4 — Release gate
Do **not** enable alerts by default or call the engine production-ready until:
- the test suite passes on the exact commit to be deployed;
- historical replay and out-of-sample results are recorded;
- paper monitoring shows stable data quality and delivery;
- the user reviews and approves the remaining provisional thresholds;
- secrets are rotated if previously exposed and stored only in service settings.

Suggested metrics: number of trades, win rate, average win/loss in R, expectancy in R per trade, maximum drawdown, consecutive losses, missed/false signals, and results after spread/slippage. Report sample size and test period beside every metric. Past results do not guarantee future performance.

## 8. Rule status ledger

| Rule | Status |
|---|---|
| 15M structure/context + 5M control and execution; 1M outcome resolution | Implemented in code; replay/tests still required |
| Close-to-close dominance | Implemented, simple 3-step proxy |
| Conflicting 5M/15M context is evidence, not an early hard rejection | Implemented; unit-tested context gates |
| Swing references | Implemented as provisional two-candle-wing proxy |
| Sweep-and-reclaim at a detected reference | Implemented, needs annotated replay |
| Post-sweep control confirmation | Implemented as directional-close sequence; thresholds remain provisional |
| Counter-bias close beyond sweep-candle boundary | Implemented for counter-bias confirmation |
| Structural stop beyond swept extreme; nearest significant 5M/15M reaction target | Implemented; validate with replay |
| Minimum planned 1:3 R:R | Implemented after configured fixed spread; missing spread returns NO_TRADE |
| User-annotated short replay helper | Implemented for research, not live signals |
| Pullback entry model | Not implemented |
| Fixed assumed spread in R:R and outcome scoring | Implemented; variable spread, commission and slippage not implemented |
| Broad historical backtest and out-of-sample proof | Not completed |
| Profitability claim | Not established |

## 9. Known replay example

The repository includes a USDJPY 5M historical fixture around 23 October 2026. It is labelled as a pattern match, not the exact screenshot timestamp. In the earlier reviewed delayed-entry example, entry 156.853, stop 156.975 and target 156.571 yielded about 1:2.31, so it fails the engine's 1:3 minimum. This example demonstrates why a visually promising move must still pass the formal risk gate; it does **not** establish strategy profitability.

## 10. Research references

The validation approach follows standard backtesting cautions: use explicit rules, realistic costs, out-of-sample data, and forward/paper testing; guard against overfitting and look-ahead bias. See:
- Binance Academy, “How to Backtest a Trading Strategy” (updated 4 June 2026): https://www.binance.com/en/academy/articles/how-to-backtest-a-trading-strategy
- QuantConnect, “Research Guide”: https://www.quantconnect.com/docs/v2/cloud-platform/backtesting/research-guide

---
**Bottom line:** this is a cautious, rule-based candidate engine, not a proven profitable system. Stronger means clearer rules, safe failure modes, reproducible tests, and evidence from unseen data—not simply more signals.

## Update 2026-10-25 — provisional threshold changes (approved for testing)

- **Sweep depth (gate D):** a 5M candle counts as a sweep when it trades beyond a 15M swing level by up to
  0.75 x the median 15M range (previously the 15% tolerance also capped sweep depth, so deeper sweeps were ignored)
  and the 5M close returns back across the level.
- **Detection window:** the sweep candle may be up to 10 completed 5M candles old (previously exactly 5-6).
- **Freshness:** the confirming close must be one of the latest 2 completed 5M candles; older confirmations are
  rejected as stale.
- **Swing levels:** equal highs/lows now count as one level (previously excluded).
- **Symbols:** default list is XAUUSD, EURUSD, GBPUSD, BTCUSD.
- **Target rule unchanged:** nearest detected 15M swing in the trade direction; it will reject most setups,
  which is the conservative failure mode. Use `replay.py` to measure rejection by gate before changing it.
- **Tooling:** `replay.py` (candle-by-candle replay with gate tally and outcomes) and `scripts/fetch_history.py`.
- Still not established: profitability, out-of-sample results, spread/slippage-aware R:R.

## Update 2026-10-25 (2) — dominance confirmation path (approved for testing)

After a 5M sweep-and-reclaim at a 15M swing level, control can now be confirmed two ways
(the earliest confirming candle wins; entry is that candle's close):

1. **Base then break** (unchanged): a compact/indecisive reaction, then a close beyond its range.
2. **Dominance closes** (new, from notes v1.3 "two or three consecutive closes with strong bodies"):
   `DOMINANCE_CLOSES = 3` consecutive closes in the trade direction (close-to-close, starting from
   the sweep candle's close), mean body/range >= 0.45, no streak candle below 0.20, and the final close
   beyond the sweep candle's extreme (above its high for BUY, below its low for SELL).

Unchanged gates: structural stop beyond the swept extreme (lowest low / highest high from sweep to
confirmation), nearest 15M swing in the trade direction as target, minimum 1:3, fresh confirmation
(latest 2 completed 5M candles), alert-only. All thresholds above are provisional and live in
`monitoring/strategy.py` constants.

Known gaps (not yet implemented): pullback entries; ranking multiple reaction areas by significance;
spread/slippage-aware R:R; evidence of profitability. Review `/replay` output across all four pairs
before relying on alerts.

## Update 2026-10-26 — reaction-area ranking, retest entries, spread-aware R:R, diagnostics

- **Reaction areas ranked by significance:** a 15M swing is a *significant* area if price reacted away from it
  by >= 1.0 x median 15M range within 4 candles, or it was touched at least twice (equal highs/lows). The target is
  the nearest significant area in the trade direction. `TARGET_MODE=nearest` restores "any swing".
- **Retest (pullback) entries:** if entering at the confirming close gives < 1:3 but a limit at the retest of the
  broken level (base edge, or the sweep candle's extreme for dominance entries) gives >= 1:3, the alert is a
  *limit idea* (`entry_style=pullback_limit`). It may never fill; replay now simulates fills (12-candle wait) and
  cancels if the stop level trades first. `PULLBACK_ENABLED=false` disables it.
- **Spread-aware R:R:** reward is reduced and risk increased by an assumed spread (`ASSUMED_SPREADS`, starting
  estimates, NOT measured Deriv spreads). Replace them with measured values.
- **Diagnostics:** `/replay SYMBOL [count] [nearest] [nopb] [nospread] [rr2]` and the `replay` MCP tool report
  gate tallies, near-miss R:R values, simulated outcomes and net R. Use variants to measure how strict the
  rules are before changing anything.
- Caveat: retest entries make R:R look better but fills are not guaranteed (and losing trades fill more often),
  so judge them by replay *outcomes*, not by planned R:R.


## Update 2026-10-26 — simplified confirmation on main
- Removed the compact/alternating base gate and the requirement for a later close beyond the full reaction range.
- After a qualifying sweep/rejection, confirmation is two consecutive completed 5M candles with directional bodies and close-to-close progress. A third matching close strengthens confirmation but is optional.
- Structural stop is anchored to the sweep candle extreme: sweep low for BUY, sweep high for SELL.
- The meaningful 15M target and minimum 1:3 planned R:R gates remain.
- This change is experimental. Run tests and replay the annotated EURUSD/GBPUSD examples before enabling alerts; no profitability claim is made.

## Update 2026-10-26 (2) — stop integrity fix after a bad R_25 alert

Alert: R_25 BUY entry 2745.77, SL 2745.636, RR 1:46.5. Price had already traded to 2741.91 (3.7 pts below that
"stop") between the sweep and the confirmation, then sold off immediately. Cause: stop anchored to the sweep
candle's low only. Fixes:
- **Stop = sweep extreme, widened to the lowest low / highest high actually reached from the sweep to the
  confirmation.** Identical to the sweep-candle anchor whenever price did not trade beyond it.
- **Minimum risk:** a stop closer than 0.5 x median 5M range is inside normal noise and is rejected (stage `risk`).
- Sweeps with exactly two completed candles after them are now evaluated (needed by the two-close rule).
- Tests updated to the two-close rule (Oct 26 simplification) and regression tests added for the above.

## Update 2026-10-26 (3) — pullback entries OFF by default; honest replay counting

- **Retest/pullback limit entries are disabled by default** (`PULLBACK_ENABLED=false`). They were an add-on that
  turned a failed 1:3 into a limit order; in the R_25 replay they often never filled, and filled ones were counted
  twice. The strategy is: enter at the confirming close, or no trade. Re-enable only to experiment.
- **Replay counts one trade per sweep** (same sweep confirmed on several candles = one setup).
- **Replay shows rejected setups' "what if taken at market"** so R:R minimums can be judged with data
  instead of guesses. R_25 window (Oct 25-26): every valid setup hit its target at market entry, but at only
  ~1:0.5 to 1:2.4 — none reached 1:3. One window is not evidence; use `/replay` on every pair and `rr2`/`rr2.5` variants.


## Update 2026-10-28 — 1M is now an execution timeframe
- The worker already fetched 1M candles, but previously the strategy only used them as an optional conflict filter and entered at the 5M close.
- The engine now requires 1M candles. After the completed 5M confirmation candle closes, it waits for two consecutive 1M directional body closes with close-to-close progress (a third matching close strengthens the signal).
- Entry and planned R:R are calculated using the final 1M confirmation close. The 1M confirmation must be fresh; the engine will not fall back to a 5M-only entry if 1M data is missing.
- This can reduce late entries or change R:R, but it can also reject setups that never confirm on 1M. It is not evidence of profitability until historical replay and tests pass.
- Setups rejected by the 1:3 R:R gate may later reach their target; that does not make the original entry valid at 1:3. The replay report should continue tracking these separately, with realistic spread/slippage and actual entry timing.

## Update 2026-10-28 — 1M replay coverage, R:R study, alert scorecard

- **Bug:** `/replay` fetched <=300 1M candles (~5h) against up to 400 5M candles (~33h). Bars with no 1M history
  were judged `data_quality` NO_TRADE, so replays showed few/no trades. Replay now fetches 1M for the whole 5M window and
  *skips* bars that 1M cannot cover instead of scoring them as failures (`bars_skipped_no_1m`).
- **R:R study:** `/replay SYMBOL N study` buckets simulated market-entry outcomes by planned R:R.
- **Automatic scorecard:** every candidate is recorded in a ledger and scored from real 1M candles (target / stop /
  expired). `/stats` shows win rate and net R per pair. Optional Supabase storage survives restarts.
- **/health** reports monitor liveness; GitHub Actions pinger added (see docs/DEPLOY_AND_TELEGRAM.md section 4).
- 1M confirmation makes entries later than a 5M-only entry, so R:R is naturally lower: check the study before judging.


## Update 2026-10-28 — nearer intraday TP selection

- Target selection now evaluates significant reaction/liquidity areas from both 5M and 15M data rather than only significant 15M swings.
- 5M targets use a more sensitive reaction-size threshold to account for smaller intraday candle ranges; repeated touches still qualify as meaningful liquidity.
- The closest eligible target in the trade direction is selected. A 15M area wins only when equally distant, not merely because it is a 15M level.
- SELL TP must be below entry; BUY TP must be above entry. The engine keeps the 1:3 minimum after assumed spread. If the nearer target fails that minimum, the engine rejects the setup rather than selecting a much farther target to make the ratio look attractive.
- SL remains anchored beyond the swept extreme, extended if price makes a more extreme high/low before confirmation.
- Added unit tests for nearest-target selection, direction checks, and significant-area filtering.
- This change corrects target-selection logic; it does not establish profitability. The full test suite and historical replay must pass before live reliance.


## Update 2026-10-28 — stricter counter-bias confirmation

- When a proposed trade opposes clear 15M dominance, two bearish/bullish candles alone are no longer enough.
- Counter-bias entries require three consecutive completed 5M candles in the proposed direction, close-to-close progress, each candle body at least 20% of its range, average body/range at least 45%, and a final close beyond the sweep candle's opposite boundary.
- If no qualifying sequence appears, the setup is rejected as **NO_TRADE**. The scan continues past weaker pairs to find a later qualifying three-candle sequence.
- Added unit tests for a valid strong counter-bias sequence, failure to break the sweep boundary, and weak candle bodies.
- These are provisional filters to be evaluated in replay; they are not evidence of profitability.


## Implementation audit — 2026-10-28

The following implementation gaps identified in the research review have now been addressed in code:

- **Conflicting context gate:** 5M-vs-15M disagreement is recorded as evidence instead of prematurely rejecting before sweep and confirmation analysis. Counter-bias confirmation now keys off structural bias when available, with close-to-close dominance as fallback.
- **Structure context:** the engine now attempts to classify bullish/bearish structure from confirmed swing progression (both swing highs and lows must progress in the same direction). This remains a heuristic and can return mixed.
- **Ambiguous double sweeps:** when the same latest 5M candle sweeps and reclaims both sides, the engine returns **NO_TRADE** because OHLC cannot reveal the order of events.
- **Unknown costs:** missing symbol spread no longer silently becomes zero. A symbol must have an explicit spread value via defaults or the ASSUMED_SPREADS environment variable; otherwise the cost-model gate returns **NO_TRADE**.
- **Honest target evidence:** the alert reports the actual selected 5M or 15M target timeframe.
- **Replay execution model:** when 1M history is available, replay resolves stop/target using 1M bars after the signal candle closes, estimates fill from the first subsequent 1M open, treats a gap beyond the target as missed rather than a win, uses the actual estimated fill for target R, and treats same-candle stop/target as a stop. It falls back to 5M resolution only when 1M data is unavailable and reports that limitation.
- **History downloader:** scripts/fetch_history.py now downloads 1M as well as 5M and 15M history, and replay.py passes 1M history to the replay engine.
- **Shadow ledger timing:** alerts are evaluated starting at the close of the 5M confirmation candle (candle_epoch + 300), not one minute after its opening timestamp. Open alerts are scored against deeper 1M history; the default fetch is 1,440 bars and can be changed with LEDGER_CANDLE_COUNT.
- **Scorecard:** the ledger now reports closed sample count, expectancy in R per closed trade, maximum drawdown in R, maximum consecutive losses, and missed gap entries in addition to win rate and net R.

### Still not completed / not proven

- Use `python scripts/fetch_history.py SYMBOL START_DATE END_DATE history.json` to fetch 15M, 5M and 1M history, then run `python scripts/validate_strategy.py history.json` for chronological 60% development / 20% validation / 20% holdout metrics. For symbols without a configured spread, pass a measured assumption using `--spread VALUE`; do not use a guessed value.
- These changes do not establish profitability. No claim of a positive edge should be made until historical replay has been run on sufficiently large, market-specific datasets with an untouched holdout period.
- The 20% single-candle and 45% mean-body thresholds, two-swing structural proxy, swing wings, reaction-size thresholds and sweep-depth thresholds remain hypotheses. They must be compared against annotated examples and tested out of sample.
- Current cost modelling is a configured spread assumption; it does not yet model variable spread at every candle, commissions, financing, latency or real order fills.
- The monitor remains candidate/scorecard only. Keep strategy alerts off until market-specific replay and paper-monitoring results are reviewed.


## Fresh-entry timing safeguard — 2026-10-28

The live engine now rejects a confirmation unless it belongs to the latest completed 5M candle. This avoids presenting a historical confirming close as a fresh entry when price has already moved since that close. Replay still evaluates each bar chronologically; shadow outcome scoring starts at the first subsequent 1M candle open when available.
