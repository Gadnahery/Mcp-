# MT5 Candle-Behaviour EA — Demo Research Build

**Status: prototype; not approved for live trading.**

## Files
- mt5/CandleBehaviourEA.mq5: MetaTrader 5 Expert Advisor source.
- docs/MT5_EA_DEMO.md: setup and safety notes.

## Current behaviour
- Reads completed candles only.
- Uses H1 close-to-close progress as dominance context.
- Requires 15M swing structure to agree with the setup.
- Searches completed 5M candles for a sweep beyond a recent range followed by a reclaim.
- Requires 2–3 consecutive directional closes on M5 after the sweep, with each close progressing beyond the previous close.
- Then waits for a fresh directional M1 response and uses the recent M1 micro-extreme plus a buffer for a tighter invalidation stop. Set UseM5Confirmation=true only for symbols where M1 entry refinement is unsuitable.
- Default order placement is enabled, but demo-account-only protection remains enabled. Default fixed order size is 0.01 lots; set UseFixedLotSize=false to use risk-based sizing.
- Uses the nearest detected opposing 5M/15M swing as target and rejects trades below 1:3 planned reward-to-risk.
- Sizes volume from equity risk; rejects if broker minimum lot exceeds the risk budget.
- Limits one position per symbol/magic, trades per day, and daily equity drawdown.
- Demo order placement is enabled by default (EnableTrading=true), but the EA refuses non-demo accounts (DemoAccountOnly=true).

## Important limitations
This is a first MT5 translation, not a proven exact replica of the Python engine or the full chart study. The M1 entry is a simplified directional response plus recent micro-extreme, not a complete detector for every absorption/rejection pattern. Swing structure, sweep/reclaim and candle strength are numerical proxies. The current prototype does not yet encode every described form of absorption/rejection and needs chart-by-chart validation against manually labelled examples. It does not call Deriv MCP: it uses the MT5 broker's own prices, symbol naming, spreads, contract specifications and execution.

## Install (desktop MT5 or compatible VPS required)
1. In desktop MT5 choose File → Open Data Folder.
2. Put CandleBehaviourEA.mq5 in MQL5/Experts/.
3. Open MetaEditor and compile; resolve all errors and warnings before use.
4. In Strategy Tester select the EA and symbol; prefer Every tick based on real ticks when available.
5. Backtest several months with realistic spread/commission and an untouched chronological holdout.
6. Attach to a demo account with EnableTrading=false first; inspect the journal and chart.
7. Only enable order placement after compilation and manual chart review, and only on demo.

## Safety defaults
- EnableTrading=true (demo only)
- UseFixedLotSize=true; FixedLotSize=0.01
- DemoAccountOnly=true and initialization is blocked on non-demo accounts.
- Minimum RR cannot be lowered below 3.0.
- Risk 0.25% per trade, maximum 3 entries/day, daily equity-loss cap 1%.
- No martingale, grid, averaging down, or lot escalation.
- Live trading must not be enabled by simply changing an input; any future live mode needs a separate reviewed change.

## Validation before considering live use
- [ ] Compile in MetaEditor with zero errors and review warnings.
- [ ] Compare H1/M15 context, M5 sweep, confirmation, SL/TP and RR with manually labelled charts.
- [ ] Test both directions, spread spikes, gaps, insufficient history, market closed, minimum lot and rejected orders.
- [ ] Verify risk sizing on symbols with different tick values and account currencies.
- [ ] Check daily limits after terminal restarts and partial/closed deals.
- [ ] Run multi-month per-symbol backtests with costs and an untouched holdout.
- [ ] Forward-test on demo. Do not claim a win rate before sufficient resolved trades.

The strategy source of truth remains candle behaviour: meaningful structure/liquidity areas, sweep, absorption/indecision or rejection, close-to-close dominance, confirmation, invalidation beyond the sweep, and the next plausible reaction area with at least 1:3 planned R:R. Missing setups must not be fixed by weakening the user's rules.
