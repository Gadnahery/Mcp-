# Candle-behaviour strategy engine: rule boundary

This document is the contract between the user's study notes and the automated engine. The study notebook is the source of truth; this implementation must not silently turn hypotheses into confirmed rules.

## Confirmed from the study notes

1. **Location first.** Establish meaningful higher-timeframe structure/liquidity/reaction area before interpreting the 1M setup.
2. **Dominance is close-to-close progress.** Compare each close with the previous candle's close. Candle colour alone is insufficient. Wicks that give back progress matter.
3. **Sweep is context, not entry.** After a sweep/false sweep, study the reaction and subsequent closes.
4. **Read the struggle.** Rejection, indecision, a possible base/absorption, buyer/seller responses and real progress help assess who is gaining control. A wick or small candle alone does not prove absorption.
5. **Control can continue or break.** Do not assume every pullback reverses a trend or that a trend must continue.
6. **Entry timing is contextual.** A decisive close can justify entry if evidence is strong and no compelling nearby reason suggests a revisit. Waiting for a pullback can be appropriate in other conditions. Never hard-code either as universal.
7. **Structural invalidation.** Stop-loss belongs beyond the relevant high/low that invalidates the idea.
8. **Target before entry.** Target a plausible next reaction/liquidity area, not automatically the exact prior high/low.
9. **Minimum planned R:R is 1:3.** If a plausible target does not offer it after execution costs, skip/reassess.
10. **No untested performance claims.** Win rate and profitability require historical replay/backtesting and forward paper testing.

## Chart examples to preserve

### Example A — study PDF page 27 (Gold, 1M)
- Price declined into a marked area around 4,061.5–4,061.7.
- The user's explanation describes buyers and sellers responding, a sweep, and then upward continuation.
- The higher-timeframe area must be identified first; the 1M sequence is evidence about momentum loss, indecision/possible absorption, sweep and which side wins.
- Exact sweep candle, entry, stop and target are still unconfirmed. Do not invent them.

### Example B — study PDF page 54 (Gold, 1M long)
- Price reaches a meaningful higher-timeframe area.
- Lows are swept (false sweep), followed by indecision/rejection and a buyer response.
- A small green candle with wicks on both sides shows uncertainty; an area above may attract sellers.
- A later bullish candle closes above that area, showing sellers did not win the close contest.
- The user entered after that decisive close because the move was impulsive and no compelling nearby reason suggested a revisit. This is an example, not a universal immediate-entry rule.

## Current engine implementation (partly provisional)

- 1H and 15M: require clear close-to-close dominance alignment. This is a conservative implementation gate, not a claim that the user's method always requires both to have identical dominance.
- 5M: records dominance and rejects a clearly progressing opposing sequence. Whether every valid pullback should be handled this way needs chart replay review.
- Higher-timeframe areas: currently approximated with detected swing highs/lows. A swing point is not automatically a meaningful area; review annotated charts and improve the area model before enabling alerts.
- Area tolerance: currently derived from a fraction of recent 15M candle ranges. This numeric tolerance is a coding heuristic, not a user-confirmed threshold.
- Possible base: currently detected using relative candle ranges and alternating candle bodies. The numeric comparison is a coding heuristic; it must not be described as confirmed absorption.
- Confirmation: looks for a completed 1M close beyond the local struggle range after the sweep.
- Entry: current prototype only models entry at the decisive close. It does not yet compare the probability/cost of immediate entry against a pullback.
- Target: nearest detected higher-timeframe swing in the trade direction; reject if it does not provide at least 1:3 before spread/slippage costs. Cost-aware target validation remains to be added.
- AI: not currently a trained model. The deterministic engine provides repeatable evidence; any future AI should explain and classify evidence, never override risk gates.

## No-alert conditions

- Missing, malformed, duplicated or stale candle data.
- No clear higher-timeframe context or conflicting context.
- No detected meaningful-location proxy.
- Sweep without a confirmed post-sweep response.
- No decisive close showing which side won the local struggle.
- Stop does not structurally invalidate the setup, or risk is non-positive.
- No plausible next reaction area, or planned reward/risk below 1:3 after costs.
- Duplicate setup already sent, missed entry, or invalidated setup.

## Validation required before live alerts

1. Replay the page 27 and page 54 chart examples candle-by-candle.
2. Confirm each automatically detected zone against the user's marked higher-timeframe areas.
3. Record false positives, missed setups, entry timing, structural stop, target, spread/slippage and outcome.
4. Keep confirmed rules, provisional heuristics and open questions separately labelled.
5. Keep Telegram alerts disabled until the user reviews the replay results.
