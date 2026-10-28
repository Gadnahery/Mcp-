"""Chronological development/validation/holdout replay for the candle strategy.

Usage:
  python scripts/validate_strategy.py history.json
  python scripts/validate_strategy.py history.json --spread 0.8

The final 20% is held out chronologically. This script does not tune parameters or
prove future profitability; it provides comparable, cost-aware sample metrics.
"""
from __future__ import annotations

import argparse
import json
from typing import Any

from monitoring.replay_engine import run_replay


def metrics(result: dict[str, Any]) -> dict[str, Any]:
    candidates = result.get("candidates", [])
    resolved = [c for c in candidates if c.get("r") is not None]
    returns = [float(c["r"]) for c in resolved]
    cumulative = peak = drawdown = 0.0
    losses = current_losses = max_losses = 0
    for value in returns:
        cumulative += value
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
        if value < 0:
            current_losses += 1
            max_losses = max(max_losses, current_losses)
        else:
            current_losses = 0
    targets = sum(1 for c in resolved if c.get("outcome") == "target")
    stops = sum(1 for c in resolved if str(c.get("outcome", "")).startswith("stop"))
    return {
        "bars_evaluated": result.get("bars_evaluated", 0),
        "candidates": len(candidates),
        "resolved": len(resolved),
        "targets": targets,
        "stops": stops,
        "win_rate": round(targets / len(resolved), 4) if resolved else None,
        "net_r": round(sum(returns), 3),
        "expectancy_r": round(sum(returns) / len(returns), 3) if returns else None,
        "max_drawdown_r": round(drawdown, 3),
        "max_consecutive_losses": max_losses,
        "open_or_unresolved": sum(1 for c in candidates if c.get("r") is None),
        "missed_or_cancelled": sum(1 for c in candidates if str(c.get("outcome", "")).startswith(("missed", "cancelled", "unfilled"))),
        "outcome_resolution_counts": {
            resolution: sum(1 for c in candidates if c.get("outcome_resolution", "unknown") == resolution)
            for resolution in sorted({c.get("outcome_resolution", "unknown") for c in candidates})
        },
        "gate_tally": result.get("tally", {}),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("history", help="JSON with symbol, m15, m5, and preferably m1 OHLC arrays")
    parser.add_argument("--spread", type=float, default=None,
                        help="Explicit assumed spread in price units; required for symbols without a configured default")
    parser.add_argument("--warmup", type=int, default=60, help="5M warmup candles before each evaluation window")
    args = parser.parse_args()

    with open(args.history, encoding="utf-8") as handle:
        data = json.load(handle)
    m5 = sorted(data["m5"], key=lambda c: int(c["epoch"]))
    m15 = sorted(data["m15"], key=lambda c: int(c["epoch"]))
    m1 = sorted(data.get("m1", []), key=lambda c: int(c["epoch"]))
    if len(m5) < max(180, args.warmup * 3) or len(m15) < 20:
        raise SystemExit("Need a longer history: at least 180 5M bars and 20 15M bars.")
    if args.spread is not None and args.spread < 0:
        raise SystemExit("--spread must be zero or positive.")
    if not m1:
        print("WARNING: no 1M history supplied. Outcome resolution falls back to 5M, so stop/target order inside a 5M candle is unknowable.")
    elif len(m1) < len(m5) * 3:
        print("WARNING: 1M history is sparse relative to 5M history; some signals may be skipped or resolved at coarser 5M precision.")
    if n < 2_000:
        print(f"WARNING: only {n} 5M bars. This is a smoke test, not a meaningful profitability sample; aim for several months per market.")

    n = len(m5)
    boundaries = (int(n * 0.60), int(n * 0.80), n)
    windows = [
        ("development", 0, boundaries[0]),
        ("validation", boundaries[0], boundaries[1]),
        ("holdout", boundaries[1], boundaries[2]),
    ]
    opts = {"spread": args.spread} if args.spread is not None else {}
    print(f"Symbol: {data.get('symbol', '?')} | 5M bars: {n} | 1M bars: {len(m1)}")
    print("Chronological split: 60% development / 20% validation / 20% holdout.")
    print("The holdout must remain untouched while any rules or thresholds are adjusted.")
    print(f"Cost assumption: {'explicit ' + str(args.spread) if args.spread is not None else 'configured symbol default; unknown symbols safely fail cost gate'}")
    print()
    for name, start, end in windows:
        context_start = max(0, start - args.warmup)
        # Bound outcome candles at this split's end so no trade can borrow future
        # bars from the next period. The last candle remains excluded as potentially forming.
        segment5 = m5[context_start:end]
        end_epoch = int(m5[end - 1]["epoch"]) + 300
        start_epoch = int(m5[context_start]["epoch"])
        segment15 = [c for c in m15 if int(c["epoch"]) < end_epoch]
        segment1 = [c for c in m1 if start_epoch <= int(c["epoch"]) < end_epoch]
        result = run_replay(
            data.get("symbol", "?"), segment15, segment5, m1=segment1,
            warmup=min(args.warmup, max(1, len(segment5) - 2)), opts=opts,
        )
        print(f"[{name.upper()}] 5M indexes {start}:{end}")
        window_metrics = metrics(result)
        resolved_count = window_metrics["resolved"]
        if name == "holdout" and resolved_count < 30:
            print(f"WARNING: holdout has only {resolved_count} resolved outcomes; treat all win-rate/expectancy estimates as highly uncertain.")
        if window_metrics["outcome_resolution"] != ["1M"]:
            print("WARNING: this window mixes or uses coarser-than-1M outcome resolution; do not compare it directly with a fully 1M-resolved window.")
        print(json.dumps(window_metrics, indent=2, sort_keys=True))
        print()
    print("Interpret results by market separately. Small samples, changing spreads, and OHLC ambiguity can invalidate conclusions.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
