# Chart replay review: page 27 and page 54

Status: **manual sequence review started; exact OHLC replay is pending source candle data**.

The study notebook records visual interpretations of the screenshots, not machine-readable OHLC candles. Do not synthesize prices and present them as the original chart.

## Case A — PDF page 27, Gold 1-minute

**Source-derived sequence**
1. Price declines toward a marked area (approximately 4,061.5–4,061.7 in prior visual discussion; recheck against the original screenshot before using numerically).
2. Buyers respond.
3. Sellers attempt to push price down again.
4. A low is swept / false-swept.
5. Price then rises.

**Engine requirements**
- The marked higher-timeframe area must be supplied/identified; a 1-minute swing algorithm is not proof of meaningful context.
- Do not alert on the sweep itself.
- Inspect the candles after the sweep and the close-to-close progress showing which side wins.
- The exact sweep candle, confirmation candle, stop, target, and R:R remain unverified for this screenshot.

**Current engine comparison**
- It has a provisional swing-reference detector and sweep/reclaim check.
- It now requires a provisional post-sweep reaction cluster and a later close beyond that cluster.
- This is directionally closer to the narrative, but cannot be marked as a successful page-27 replay without the screenshot-derived candle data and correct higher-timeframe context.

## Case B — PDF page 54, long setup

**User-confirmed sequence**
1. Price reaches a higher-timeframe structure/liquidity area.
2. Price false-sweeps the lows.
3. Indecision and rejection follow.
4. A second green candle adds evidence of buyer response.
5. Another small green candle has a small body and wicks on both sides; sellers may react above.
6. The next bullish candle closes above the selling area.
7. Entry is taken after that decisive close because the move is impulsive and no compelling nearby area makes a revisit necessary.

**Engine requirements**
- Post-sweep behaviour must be examined; the sweep alone is not an entry.
- The confirmation must be a completed candle close beyond the relevant local struggle/selling area.
- Entry at the decisive close is context-dependent, not a universal rule.
- Stop must invalidate the idea; target must be a plausible next reaction area and planned R:R must be at least 1:3 after realistic costs.

**Current engine comparison**
- A logic mismatch was fixed: the previous implementation assessed its possible base mainly before the sweep. It now assesses a possible reaction cluster after the sweep, then requires a later close beyond that cluster.
- The cluster detector is still a rough coding proxy; it does not yet understand the chart's manually marked selling area or human interpretation of rejection.
- It still cannot decide reliably whether immediate entry or a pullback is better. No automatic alert should be treated as a trade instruction.

## Required next replay data

For each case, capture timestamped OHLC candles from the original chart (or export the exact instrument/time range), plus the higher-timeframe area marked by the user. Then record each candle's role: approach, sweep, rejection/indecision, uncertain struggle, decisive close, entry, invalidation, target. Compare the detector's output with this annotation and log false positives and missed setups.

Until this data is supplied and replayed, status remains **not validated**. The current code should remain in the research branch with alerts disabled.


## Case C — USD/JPY 5-minute annotated short (user-provided screenshot)

**Chart facts visible in the screenshot**
- Instrument/timeframe: U.S. Dollar / Japanese Yen, 5-minute, OANDA.
- Screenshot timestamp: 24 October 2026, 18:26 UTC+3.
- Marked sweep/rejection area: near 156.96.
- Marked sell confirmation area: approximately 156.90–156.87.
- Marked sell entry: 156.874.
- Marked stop-loss: 156.975.
- Marked take-profit: 156.571, labelled 3R.
- The visible subsequent decline trades well below the marked target before price rebounds. This suggests the displayed move reached the target level, although the screenshot alone does not establish exact fill/execution quality.

**Arithmetic check**
- Planned risk: 156.975 − 156.874 = 0.101.
- Planned reward: 156.874 − 156.571 = 0.303.
- Planned reward/risk: 0.303 / 0.101 = exactly 3.00R before spread, slippage, and other costs.

**Candle-sequence interpretation**
1. Price rallies into the marked high/rejection area near 156.96.
2. The high-area test is context, not by itself a sell trigger.
3. Price retreats and enters the marked 156.90–156.87 confirmation area.
4. The intended short is taken near 156.874 after seller confirmation.
5. The invalidation is above the marked rejection high at 156.975.
6. The target is 156.571; the displayed later decline crosses that price level.

**What remains unknown**
- The exact timestamp/OHLC of the sweep candle and decisive confirmation candle are not readable from this annotated screenshot.
- Exact candle-by-candle closes, spread at entry, slippage, and actual order fill are not supplied.
- The screenshot does not show the 1H context or 15M refinement, so those parts of the user's preferred workflow cannot be independently verified here.

**Engine replay acceptance criteria**
- Do not generate a short from the sweep alone.
- Require the post-sweep seller response and a completed bearish close that supports the marked confirmation area.
- Use the rejection high as the invalidation reference only if candle data confirms it is the relevant swing.
- Verify the next reaction target and 1:3 planned R:R after realistic costs.
- Treat 156.874 / 156.975 / 156.571 as the user's annotated example levels, not universal fixed distances or an automatically inferred setup.
- To score the detector, obtain exact timestamped OHLC candles for this interval and compare the detected signal candle with the user's intended confirmation candle.

This screenshot is now a concrete visual reference case, but it is **not yet an exact OHLC replay fixture**. Keep alerts disabled until replay can be tested against timestamped candle data.
