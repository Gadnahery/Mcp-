# Candle-Behaviour Strategy Engine — Rulebook & Validation Plan

**Status:** research implementation; not approved for live trading  
**Engine:** Deriv MCP strategy monitor  
**Timeframes:** 15-minute context + 5-minute execution only  
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
| 15M | Context, meaningful swing references, reaction areas | Detect provisional swing highs/lows and broad close-to-close dominance |
| 5M | Approach, sweep/reclaim, post-sweep response, confirmation and entry | Evaluate the sequence and calculate entry, stop, target and planned R:R |

The 1H and 1M timeframes are intentionally **not used** by the strategy engine. Do not reintroduce them as mandatory filters without an explicit strategy review and regression tests.

## 3. Setup sequence

### Gate A — Data quality
- Require at least 20 valid candles on both timeframes.
- Candle OHLC must be finite and internally consistent: low ≤ open/close ≤ high.
- Sort by epoch and collapse duplicate timestamps.
- Exclude the newest candle from signal logic because it may still be forming.
- The monitor separately rejects stale or implausibly future completed candles.
- If data is missing or unusable, return **NO_TRADE**.

### Gate B — 15M context and reference levels
- Estimate dominance from three consecutive close-to-close advances or declines.
- If the three changes are not all strictly positive or all strictly negative, context is mixed/unclear.
- Detect local swing highs/lows using a two-candle wing on either side. This is a **provisional coding proxy**, not a fully specified user-confirmed swing rule.
- Reaction-area tolerance is currently 15% of the median range of the last 20 completed 15M candles. This threshold is provisional and requires annotated-chart validation.

### Gate C — 5M approach/conflict
- Record 5M close-to-close dominance when present.
- Reject for continuing opposition only when **both** timeframes have clear dominance and 5M is still clearly advancing against the 15M direction.
- Unclear 15M context must not be treated as an opposing direction.
- A contrary-direction sweep may still be considered, but must pass the same strong confirmation and risk gates.

### Gate D — Sweep and reclaim
- BUY candidate context: price trades below a detected 15M swing low and the same 5M candle closes back above that reference.
- SELL candidate context: price trades above a detected 15M swing high and the same 5M candle closes back below that reference.
- The detector searches recent 5M candles and now leaves only the two candles needed for the new confirmation rule; recent valid sweeps are not discarded merely because they lack an old three-candle reaction window.
- A sweep alone never produces a candidate.

### Gate E — Post-sweep reaction and control confirmation
- Require enough candles before and after the sweep to inspect the reaction.
- The simplified confirmation rule now requires **two consecutive completed 5M candles** with bodies in the trade direction and close-to-close progress after the sweep/rejection.
- A third matching candle is used when present to strengthen confirmation; it is not mandatory.
- The engine no longer requires an extra compact/alternating base or a later close beyond the entire three-candle reaction range.
- Current automated entry is the final confirmation candle's close. Pullback-limit entry remains a separate optional execution style and is not yet implemented in the live candidate engine.

### Gate F — Invalidation, target and reward-to-risk
- BUY stop: sweep candle's low (the low that performed the sweep).
- SELL stop: sweep candle's high (the high that performed the sweep).
- Target: nearest detected 15M swing reference in the trade direction beyond entry.
- Risk and reward must both be positive.
- Planned reward-to-risk must be at least 3.0; otherwise return **NO_TRADE**.
- This is a planned ratio before spread, slippage, execution delay and other costs. The actual ratio can be worse.
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
4. **Execution assumptions:** entry-at-close may not be fillable at that price after the candle closes. Spread/slippage and latency are not included in the 1:3 calculation.
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
| 15M context + 5M execution; no 1H/1M dependency | Implemented |
| Close-to-close dominance | Implemented, simple 3-step proxy |
| Unclear 15M is not automatically an opposing filter | Implemented and unit-tested |
| Swing references | Implemented as provisional two-candle-wing proxy |
| Sweep-and-reclaim at a detected reference | Implemented, needs annotated replay |
| Post-sweep compact/alternating base requirement | Removed from signal gate |
| Two consecutive directional body closes with close-to-close progress | Implemented |
| Optional third matching close strengthens confirmation | Implemented |
| Structural stop and nearest detected 15M swing target | Implemented |
| Minimum planned 1:3 R:R | Implemented before costs |
| User-annotated short replay helper | Implemented for research, not live signals |
| Pullback entry model | Not implemented |
| Spread/slippage-aware R:R | Not implemented |
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


## Update 2026-10-26 — simplified confirmation
- Removed the compact/alternating base gate and the requirement to close beyond the full reaction range.
- After a qualifying sweep-and-rejection, confirmation is two consecutive directional body closes with progress in consecutive closing prices; a third matching close strengthens the evidence.
- Structural stop is anchored to the sweep candle's extreme, as requested.
- The 1:3 target gate, 15M target reference, completed-candle exclusion, freshness gate and disabled-by-default alerts remain.
- This is a code change, not evidence of profitability. Run unit tests and replay the annotated EURUSD/GBPUSD cases before enabling live alerts.
