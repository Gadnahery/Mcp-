"""Conservative, transparent candle-behaviour candidate detector.

This is a first-pass research implementation, not a validated profitable strategy.
It deliberately returns no signal when context is incomplete or ambiguous.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Candidate:
    symbol: str
    side: str
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    candle_epoch: int
    explanation: str
    invalidation: str


def _valid(c: dict[str, Any]) -> bool:
    try:
        o, h, l, close = (float(c[k]) for k in ("open", "high", "low", "close"))
        return l <= min(o, close) <= max(o, close) <= h
    except (KeyError, TypeError, ValueError):
        return False


def _dominance(candles: list[dict[str, Any]], n: int = 3) -> str | None:
    """Use consecutive close-to-close progress, not candle colour."""
    if len(candles) < n + 1:
        return None
    closes = [float(c["close"]) for c in candles[-(n + 1):]]
    changes = [b - a for a, b in zip(closes, closes[1:])]
    if all(change > 0 for change in changes):
        return "bullish"
    if all(change < 0 for change in changes):
        return "bearish"
    return None


def detect_candidate(
    symbol: str,
    candles_1h: list[dict[str, Any]],
    candles_15m: list[dict[str, Any]],
    candles_5m: list[dict[str, Any]],
    candles_1m: list[dict[str, Any]],
) -> Candidate | None:
    """Find a *candidate* only when a recent 1m sweep/reclaim aligns with context.

    Deliberately conservative initial conditions:
    - all four timeframes have enough valid candles;
    - 1H and 15M close-to-close dominance agree;
    - latest completed 1m candle sweeps the recent 1m range and closes back inside;
    - following 1m candle confirms with a close beyond the sweep candle's open;
    - a structural stop and a 3R target can be calculated from the confirmation close.

    This mechanical proxy is not a full implementation of every rule in the study notes.
    Review in historical replay before enabling live alerts.
    """
    series = (candles_1h, candles_15m, candles_5m, candles_1m)
    if any(len(c) < 10 or any(not _valid(x) for x in c[-10:]) for c in series):
        return None

    # Exclude the newest candle because it may still be forming.
    h1, m15, m5, m1 = [c[:-1] for c in series]
    if min(map(len, (h1, m15, m5, m1))) < 6:
        return None

    h1_dom = _dominance(h1, 3)
    m15_dom = _dominance(m15, 3)
    if h1_dom is None or h1_dom != m15_dom:
        return None

    # Avoid a trade against a clearly progressing 5m sequence.
    m5_dom = _dominance(m5, 3)
    if m5_dom is not None and m5_dom != h1_dom:
        return None

    # Look for a sweep/reclaim of the previous five completed 1m candles.
    prior = m1[-7:-2]
    sweep = m1[-2]
    confirm = m1[-1]
    range_high = max(float(c["high"]) for c in prior)
    range_low = min(float(c["low"]) for c in prior)
    side: str
    if h1_dom == "bullish" and float(sweep["low"]) < range_low and float(sweep["close"]) > range_low:
        if float(confirm["close"]) <= float(sweep["open"]):
            return None
        side = "BUY"
        stop = min(float(sweep["low"]), float(confirm["low"]))
        entry = float(confirm["close"])
        risk = entry - stop
        if risk <= 0:
            return None
        target = entry + 3 * risk
        reason = (
            "1H and 15M show rising close-to-close dominance; "
            "1M swept below the recent range and closed back inside, "
            "then the next completed candle confirmed upward."
        )
        invalidation = f"Setup invalid if price trades below {stop:.5f}."
    elif h1_dom == "bearish" and float(sweep["high"]) > range_high and float(sweep["close"]) < range_high:
        if float(confirm["close"]) >= float(sweep["open"]):
            return None
        side = "SELL"
        stop = max(float(sweep["high"]), float(confirm["high"]))
        entry = float(confirm["close"])
        risk = stop - entry
        if risk <= 0:
            return None
        target = entry - 3 * risk
        reason = (
            "1H and 15M show falling close-to-close dominance; "
            "1M swept above the recent range and closed back inside, "
            "then the next completed candle confirmed downward."
        )
        invalidation = f"Setup invalid if price trades above {stop:.5f}."
    else:
        return None

    # Do not duplicate one candidate for the same symbol/candle.
    return Candidate(
        symbol=symbol,
        side=side,
        entry=entry,
        stop_loss=stop,
        take_profit=target,
        risk_reward=3.0,
        candle_epoch=int(confirm["epoch"]),
        explanation=reason + " This is an experimental rule-based candidate, not a validated trade signal.",
        invalidation=invalidation,
    )
