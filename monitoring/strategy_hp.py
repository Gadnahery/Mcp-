"""High-probability candle-logic engine (research-backed on XAUUSD HistData 2025-2026).

Candle theory encoded:
- 15M close-to-close dominance: who is winning the higher-timeframe auction
- Sweep + rejection wick of a swing against dominance: failed breakout / liquidity grab
- 5M confirmation: strong directional bodies that close in the dominant side of the bar
  (buyers close near high, sellers near low) with close-to-close progress
- Stop beyond the sweep extreme (invalidates the failed-auction idea)
- Target at a fixed modest R multiple (closer targets raise hit rate vs far structure TPs)

Backtest (XAUUSD, ~21 months HistData): best balanced ~2.3–3.2 trades/week at ~65–68% WR,
net positive R. 80% WR at 3/week was not achieved without tiny sample sizes.
"""
from __future__ import annotations

import os
from statistics import median
from typing import Any

from .strategy import (
    ASSUMED_SPREADS,
    Analysis,
    Candidate,
    Side,
    _completed,
    _dominance,
    _swing_levels,
)

HP_TARGET_RR = float(os.getenv("HP_TARGET_RR", "0.7"))
HP_MIN_BODY = float(os.getenv("HP_MIN_BODY", "0.45"))
HP_CLOSE_EDGE = float(os.getenv("HP_CLOSE_EDGE", "0.70"))
HP_CONFIRM_N = int(os.getenv("HP_CONFIRM_N", "2"))
HP_DOM_N = int(os.getenv("HP_DOM_N", "3"))
HP_WICK_RATIO = float(os.getenv("HP_WICK_RATIO", "0.25"))


def analyze_setup_hp(
    symbol: str,
    candles_15m: list[dict[str, Any]],
    candles_5m: list[dict[str, Any]],
    opts: dict[str, Any] | None = None,
) -> Analysis:
    opts = opts or {}
    target_rr = float(opts.get("target_rr", HP_TARGET_RR))
    min_body = float(opts.get("min_body", HP_MIN_BODY))
    close_edge = float(opts.get("close_edge", HP_CLOSE_EDGE))
    confirm_n = int(opts.get("confirm_n", HP_CONFIRM_N))
    dom_n = int(opts.get("dom_n", HP_DOM_N))
    wick_ratio = float(opts.get("wick_ratio", HP_WICK_RATIO))

    data = {"15M": _completed(candles_15m), "5M": _completed(candles_5m)}
    evidence: list[str] = []
    missing: list[str] = []
    for tf, cs in data.items():
        if len(cs) < 20:
            missing.append(f"{tf}: need >=20 candles")
    if missing:
        return Analysis(symbol, "NO_TRADE", None, "data_quality", tuple(evidence), tuple(missing))
    for tf in data:
        data[tf] = data[tf][:-1]
    m15, m5 = data["15M"], data["5M"]
    if len(m5) < 40 or len(m15) < 20:
        return Analysis(symbol, "NO_TRADE", None, "data_quality", tuple(evidence), ("Insufficient completed candles",))

    dom = _dominance(m15, dom_n)
    if not dom:
        return Analysis(symbol, "NO_TRADE", None, "htf_alignment", tuple(evidence), (f"No clear {dom_n}-bar 15M close-to-close dominance",))
    side: Side = "BUY" if dom == "bullish" else "SELL"
    evidence.append(f"15M dominance ({dom_n} closes): {dom} → only {side} setups")

    ref_highs, ref_lows = _swing_levels(m15[-80:])
    levels = ref_lows if side == "BUY" else ref_highs
    if not levels:
        return Analysis(symbol, "NO_TRADE", side, "location_or_sweep", tuple(evidence), ("No 15M swing reference to sweep",))

    lookback = 12
    sweep = None
    sweep_index = None
    swept_level = None
    first = max(5, len(m5) - lookback)
    for i in range(first, len(m5) - confirm_n):
        c = m5[i]
        hi, lo, cl, op = float(c["high"]), float(c["low"]), float(c["close"]), float(c["open"])
        rng = hi - lo
        if rng <= 0:
            continue
        if side == "BUY":
            hit = [lv for lv in levels if lo < lv and cl > lv]
            if not hit:
                continue
            if (min(op, cl) - lo) / rng < wick_ratio:
                continue
            sweep, sweep_index, swept_level = c, i, max(hit)
        else:
            hit = [lv for lv in levels if hi > lv and cl < lv]
            if not hit:
                continue
            if (hi - max(op, cl)) / rng < wick_ratio:
                continue
            sweep, sweep_index, swept_level = c, i, min(hit)
    if sweep is None or sweep_index is None:
        return Analysis(symbol, "NO_TRADE", side, "location_or_sweep", tuple(evidence), ("No rejection-wick sweep of 15M swing against dominance",))
    evidence.append(f"Sweep/rejection of {swept_level:.5f} with wick (failed auction against {dom} control)")

    after = m5[sweep_index + 1 :]
    if len(after) < confirm_n or len(after) > confirm_n + 2:
        return Analysis(symbol, "NO_TRADE", side, "stale_confirmation", tuple(evidence), ("Confirmation not completed on the latest bars",))
    streak = after[-confirm_n:]
    for k, c in enumerate(streak):
        hi, lo, cl, op = float(c["high"]), float(c["low"]), float(c["close"]), float(c["open"])
        rng = hi - lo
        br = abs(cl - op) / rng if rng > 0 else 0.0
        cp = (cl - lo) / rng if rng > 0 else 0.5
        if br < min_body:
            return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), ("Confirmation body too weak",))
        if side == "BUY":
            if not (cl > op and cp >= close_edge):
                return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), ("BUY confirm must close in upper part of bar",))
            if k > 0 and cl <= float(streak[k - 1]["close"]):
                return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), ("No close-to-close bullish progress",))
        else:
            if not (cl < op and cp <= 1.0 - close_edge):
                return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), ("SELL confirm must close in lower part of bar",))
            if k > 0 and cl >= float(streak[k - 1]["close"]):
                return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), ("No close-to-close bearish progress",))
    final = streak[-1]
    if side == "BUY" and float(final["close"]) <= float(sweep["high"]):
        return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), ("BUY confirm has not closed above sweep high",))
    if side == "SELL" and float(final["close"]) >= float(sweep["low"]):
        return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), ("SELL confirm has not closed below sweep low",))
    evidence.append(f"{confirm_n} strong directional confirms with close location + progress")

    confirm_index = next(i for i, c in enumerate(m5) if int(c["epoch"]) == int(final["epoch"]))
    # Allow confirm within last 2 completed bars (research window)
    if confirm_index < len(m5) - 3:
        return Analysis(symbol, "NO_TRADE", side, "stale_confirmation", tuple(evidence), ("Confirmation too old",))

    entry = float(final["close"])
    if side == "BUY":
        stop = min(float(sweep["low"]), min(float(c["low"]) for c in m5[sweep_index : confirm_index + 1]))
        target = entry + target_rr * abs(entry - stop)
    else:
        stop = max(float(sweep["high"]), max(float(c["high"]) for c in m5[sweep_index : confirm_index + 1]))
        target = entry - target_rr * abs(entry - stop)
    risk = abs(entry - stop)
    if risk <= 0:
        return Analysis(symbol, "NO_TRADE", side, "risk", tuple(evidence), ("Non-positive risk",))
    ranges = [float(c["high"]) - float(c["low"]) for c in m5[-20:]]
    med = median(ranges) if ranges else 0.0
    if med > 0 and risk < med * 0.45:
        return Analysis(symbol, "NO_TRADE", side, "risk", tuple(evidence), ("Stop inside normal 5M noise",))
    spread = float(opts.get("spread", ASSUMED_SPREADS.get(symbol, 0.0)))
    risk_net = risk + spread
    reward_net = abs(target - entry) - spread
    rr = reward_net / risk_net if risk_net > 0 and reward_net > 0 else 0.0
    if rr < 0.5:
        return Analysis(symbol, "NO_TRADE", side, "risk_reward", tuple(evidence), (f"Net R:R only 1:{rr:.2f} after spread",))
    evidence.append(f"One-way entry {entry:.5f}; SL {stop:.5f}; TP {target:.5f} (HP fixed ~1:{target_rr:g})")
    candidate = Candidate(
        symbol=symbol,
        side=side,
        entry=entry,
        stop_loss=stop,
        take_profit=target,
        risk_reward=rr,
        candle_epoch=int(final["epoch"]),
        explanation=" ".join(evidence) + " HP candle-logic research candidate.",
        invalidation=f"Setup invalid if price trades {'below' if side == 'BUY' else 'above'} {stop:.5f}.",
        evidence=tuple(evidence),
        entry_style="dominance_closes",
        sweep_epoch=int(sweep["epoch"]),
        target_reference=f"fixed R multiple 1:{target_rr:g}",
    )
    return Analysis(symbol, "CANDIDATE", side, "risk_approved_candidate", tuple(evidence), (), candidate)
