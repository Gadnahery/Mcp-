"""Candle-by-candle replay of the strategy engine over saved OHLC history.

Usage:
  python replay.py history.json [--symbol XAUUSD]

history.json: {"symbol": "...", "m15": [{epoch,open,high,low,close},...], "m5": [...]}
Each 5M candle close is treated as 'now'; the engine only sees candles completed by then
(plus one forming candle, which it drops itself). Prints a gate-by-gate rejection tally and
every candidate with entry/stop/target, plus what price did afterwards (stop, target, or neither).
This measures the rules; it is not proof of profitability (costs and slippage are excluded).
"""
from __future__ import annotations

import json
import sys
from collections import Counter

from monitoring.strategy import analyze_setup


def replay(symbol: str, m15: list[dict], m5: list[dict], warmup: int = 60):
    tally: Counter[str] = Counter()
    candidates = []
    seen = set()
    for idx in range(warmup, len(m5) - 1):
        now_epoch = int(m5[idx]["epoch"]) + 300  # candle idx has just closed
        view5 = m5[: idx + 2]                     # completed + 1 forming
        view5 = [c for c in view5 if int(c["epoch"]) <= now_epoch]
        view15 = [c for c in m15 if int(c["epoch"]) <= now_epoch]
        result = analyze_setup(symbol, view15, view5)
        tally[result.stage if result.status != "CANDIDATE" else "CANDIDATE"] += 1
        if result.candidate and result.candidate.candle_epoch not in seen:
            seen.add(result.candidate.candle_epoch)
            c = result.candidate
            outcome = "open"
            for f in m5[idx + 1:]:
                hit_stop = f["low"] <= c.stop_loss if c.side == "BUY" else f["high"] >= c.stop_loss
                hit_tp = f["high"] >= c.take_profit if c.side == "BUY" else f["low"] <= c.take_profit
                if hit_stop and hit_tp:
                    outcome = "stop (same candle; assumed worst case)"
                    break
                if hit_stop:
                    outcome = "stop"
                    break
                if hit_tp:
                    outcome = "target"
                    break
            candidates.append((c, outcome))
    return tally, candidates


def main() -> int:
    if len(sys.argv) < 2:
        print(__doc__)
        return 1
    data = json.load(open(sys.argv[1]))
    tally, cands = replay(data.get("symbol", "?"), data["m15"], data["m5"])
    print("Gate tally (stage where each evaluation stopped):")
    for stage, n in tally.most_common():
        print(f"  {stage:28} {n}")
    print(f"\nCandidates: {len(cands)}")
    for c, outcome in cands:
        print(f"  {c.side} @{c.entry} stop {c.stop_loss} tp {c.take_profit} RR 1:{c.risk_reward:.2f} -> {outcome}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
