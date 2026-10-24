"""Staged candle-behaviour strategy engine.

Source-of-truth concepts:
- location before entry;
- dominance means close-to-close progress, not candle colour;
- a sweep alone is never an entry;
- read rejection, indecision/base and the response after them;
- entry after a decisive close or on a pullback is context-dependent;
- stop beyond the price that invalidates the idea;
- next plausible reaction area must leave at least 1:3 planned R:R.

Important: the study notes leave some thresholds and structure-zone definitions open.
The swing-point and candle-pattern detectors below are explicitly provisional proxies,
not user-confirmed strategy rules. Live alerts remain disabled by default until replay review.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from statistics import median
from typing import Any, Literal

Side = Literal["BUY", "SELL"]


@dataclass(frozen=True)
class Candidate:
    symbol: str
    side: Side
    entry: float
    stop_loss: float
    take_profit: float
    risk_reward: float
    candle_epoch: int
    explanation: str
    invalidation: str
    evidence: tuple[str, ...] = field(default_factory=tuple)
    entry_style: str = "decisive_close"
    target_reference: str = "next detected reaction area"


@dataclass(frozen=True)
class Analysis:
    symbol: str
    status: str
    side: str | None
    stage: str
    evidence: tuple[str, ...]
    missing: tuple[str, ...]
    candidate: Candidate | None = None


def _valid(c: dict[str, Any]) -> bool:
    try:
        o, h, l, close = (float(c[k]) for k in ("open", "high", "low", "close"))
        epoch = int(c["epoch"])
        return epoch > 0 and all(map(lambda x: x == x and abs(x) != float("inf"), (o, h, l, close))) and l <= min(o, close) <= max(o, close) <= h
    except (KeyError, TypeError, ValueError, OverflowError):
        return False


def _completed(candles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The caller supplies ordered candles; the last candle may still be forming."""
    clean = [c for c in candles if _valid(c)]
    clean.sort(key=lambda c: int(c["epoch"]))
    # Duplicate epochs can create false consecutive-close evidence; keep the last copy.
    by_epoch = {int(c["epoch"]): c for c in clean}
    return [by_epoch[k] for k in sorted(by_epoch)]


def _dominance(candles: list[dict[str, Any]], n: int = 3) -> str | None:
    """n consecutive close-to-close advances/declines; no candle-colour shortcut."""
    if len(candles) < n + 1:
        return None
    closes = [float(c["close"]) for c in candles[-(n + 1):]]
    changes = [b - a for a, b in zip(closes, closes[1:])]
    if all(change > 0 for change in changes):
        return "bullish"
    if all(change < 0 for change in changes):
        return "bearish"
    return None


def _swing_levels(candles: list[dict[str, Any]], wing: int = 2) -> tuple[list[float], list[float]]:
    """Return confirmed local swing highs/lows. Wing=2 is a provisional coding proxy."""
    highs: list[float] = []
    lows: list[float] = []
    if len(candles) < 2 * wing + 1:
        return highs, lows
    for i in range(wing, len(candles) - wing):
        window = candles[i - wing:i + wing + 1]
        hi = float(candles[i]["high"])
        lo = float(candles[i]["low"])
        if hi == max(float(c["high"]) for c in window) and sum(float(c["high"]) == hi for c in window) == 1:
            highs.append(hi)
        if lo == min(float(c["low"]) for c in window) and sum(float(c["low"]) == lo for c in window) == 1:
            lows.append(lo)
    return highs, lows


def _near_any(price: float, levels: list[float], tolerance: float) -> float | None:
    matches = [level for level in levels if abs(price - level) <= tolerance]
    return min(matches, key=lambda level: abs(price - level)) if matches else None


def _indecision_or_base(candles: list[dict[str, Any]], count: int = 3) -> tuple[bool, str]:
    """Describe a possible base using relative candle ranges; heuristic, not confirmed threshold."""
    if len(candles) < count:
        return False, "Not enough candles to assess a possible base"
    cluster = candles[-count:]
    ranges = [float(c["high"]) - float(c["low"]) for c in cluster]
    prior = candles[-(count + 6):-count]
    if not prior:
        return False, "No preceding candles to compare with the cluster"
    baseline = median(float(c["high"]) - float(c["low"]) for c in prior)
    cluster_span = max(float(c["high"]) for c in cluster) - min(float(c["low"]) for c in cluster)
    # The relative range check is only a provisional way to surface a candidate base.
    compact = baseline > 0 and median(ranges) <= baseline and cluster_span <= baseline * count * 1.25
    alternating = any(
        (float(cluster[i]["close"]) - float(cluster[i]["open"])) *
        (float(cluster[i - 1]["close"]) - float(cluster[i - 1]["open"])) < 0
        for i in range(1, len(cluster))
    )
    if compact and alternating:
        return True, "Possible compact, alternating base; subsequent close must show who won"
    if compact:
        return True, "Possible compact pause; alternating behaviour is not clear"
    return False, "No clear compact base detected"


def analyze_setup(
    symbol: str,
    candles_1h: list[dict[str, Any]],
    candles_15m: list[dict[str, Any]],
    candles_5m: list[dict[str, Any]],
    candles_1m: list[dict[str, Any]],
) -> Analysis:
    """Evaluate the setup as a sequence; returns a reasoned no-trade result when incomplete."""
    raw = {"1H": candles_1h, "15M": candles_15m, "5M": candles_5m, "1M": candles_1m}
    data = {tf: _completed(cs) for tf, cs in raw.items()}
    evidence: list[str] = []
    missing: list[str] = []
    for tf, cs in data.items():
        if len(cs) < 20:
            missing.append(f"{tf}: at least 20 valid candles required for context/reaction checks")
        if len(cs) >= 2 and int(cs[-1]["epoch"]) <= int(cs[-2]["epoch"]):
            missing.append(f"{tf}: candle order is not strictly increasing")
    if missing:
        return Analysis(symbol, "NO_TRADE", None, "data_quality", tuple(evidence), tuple(missing))

    # Exclude the newest candle in each stream because it may still be forming.
    for tf in data:
        data[tf] = data[tf][:-1]
    h1, m15, m5, m1 = data["1H"], data["15M"], data["5M"], data["1M"]

    h1_dom = _dominance(h1, 3)
    m15_dom = _dominance(m15, 3)
    if h1_dom:
        evidence.append(f"1H close-to-close dominance: {h1_dom}")
    else:
        missing.append("1H: no clear three-step close-to-close dominance")
    if m15_dom:
        evidence.append(f"15M close-to-close dominance: {m15_dom}")
    else:
        missing.append("15M: no clear three-step close-to-close dominance")
    if not h1_dom or not m15_dom or h1_dom != m15_dom:
        if h1_dom and m15_dom and h1_dom != m15_dom:
            missing.append("1H and 15M dominance disagree; context is not aligned")
        return Analysis(symbol, "NO_TRADE", None, "higher_timeframe_context", tuple(evidence), tuple(missing))

    # Identify nearby higher-timeframe reaction references. These are mechanically
    # detected swing points; the notes do not yet define a fully automatic zone algorithm.
    h1_highs, h1_lows = _swing_levels(h1[-80:])
    m15_highs, m15_lows = _swing_levels(m15[-100:])
    ref_highs = sorted(set(h1_highs + m15_highs))
    ref_lows = sorted(set(h1_lows + m15_lows))
    recent_15m_ranges = [float(c["high"]) - float(c["low"]) for c in m15[-20:]]
    tolerance = median(recent_15m_ranges) * 0.15 if recent_15m_ranges else 0.0
    if tolerance <= 0:
        return Analysis(symbol, "NO_TRADE", None, "location", tuple(evidence), ("Could not estimate a usable reaction-area tolerance",))

    # 5M is the approach/context layer: record weakening progress or conflict.
    m5_dom = _dominance(m5, 3)
    if m5_dom:
        evidence.append(f"5M close-to-close dominance: {m5_dom}")
    else:
        evidence.append("5M dominance is mixed/unclear; inspect the candle sequence at the area")
    if m5_dom and m5_dom != h1_dom:
        # A contrary 5M sequence can be a pullback, but we need to see that it has
        # stopped making progress before considering a reversal.
        recent_5m = m5[-5:]
        if _dominance(recent_5m, 3) == m5_dom:
            return Analysis(symbol, "NO_TRADE", None, "approach", tuple(evidence), ("5M is still making clear progress against the 1H/15M direction; no confirmed loss of that control",))

    # Look for the most recent sweep at a meaningful higher-timeframe swing reference.
    # A sweep is only a stage; it cannot itself produce a candidate.
    side: Side | None = None
    sweep: dict[str, Any] | None = None
    swept_level: float | None = None
    recent = m1[-12:]
    if h1_dom == "bullish":
        for i in range(max(0, len(recent) - 6), len(recent) - 2):
            candle = recent[i]
            low = float(candle["low"])
            close = float(candle["close"])
            level = _near_any(low, ref_lows, tolerance)
            if level is not None and low < level and close > level:
                side, sweep, swept_level = "BUY", candle, level
    else:
        for i in range(max(0, len(recent) - 6), len(recent) - 2):
            candle = recent[i]
            high = float(candle["high"])
            close = float(candle["close"])
            level = _near_any(high, ref_highs, tolerance)
            if level is not None and high > level and close < level:
                side, sweep, swept_level = "SELL", candle, level

    if side is None or sweep is None or swept_level is None:
        return Analysis(symbol, "NO_TRADE", None, "location_or_sweep", tuple(evidence), (
            "No recent 1M sweep-and-reclaim was found at a detected 1H/15M swing reference",
            "A swing reference is only a proxy for a meaningful area; review the chart context",
        ))
    evidence.append(f"1M swept and reclaimed detected higher-timeframe reference {swept_level:.5f}")
    evidence.append("Sweep treated as context only; waiting for post-sweep rejection/response and a decisive close")

    sweep_index = next((i for i, c in enumerate(m1) if int(c["epoch"]) == int(sweep["epoch"])), None)
    if sweep_index is None or sweep_index < 8 or sweep_index + 1 >= len(m1):
        return Analysis(symbol, "NO_TRADE", side, "post_sweep_reaction", tuple(evidence), ("Insufficient candles before/after sweep to assess the reaction",))

    before_cluster = m1[max(0, sweep_index - 3):sweep_index]
    after_sweep = m1[sweep_index + 1:]
    if not after_sweep:
        return Analysis(symbol, "NO_TRADE", side, "post_sweep_reaction", tuple(evidence), ("No completed candle after sweep",))
    base, base_note = _indecision_or_base(before_cluster + [sweep], count=3)
    evidence.append(base_note)
    if not base:
        missing.append("No sufficiently clear indecision/base candidate around the sweep (provisional detector)")
    post = after_sweep[-min(4, len(after_sweep)):]
    confirm: dict[str, Any] | None = None
    if side == "BUY":
        confirm = next((c for c in post if float(c["close"]) > max(float(x["high"]) for x in before_cluster + [sweep])), None)
    else:
        confirm = next((c for c in post if float(c["close"]) < min(float(x["low"]) for x in before_cluster + [sweep])), None)
    if confirm is None:
        return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), tuple(missing + ["No decisive completed close beyond the local struggle range after the sweep"]))
    evidence.append(f"Post-sweep candle closed decisively beyond the local struggle range at {float(confirm['close']):.5f}")
    if base:
        evidence.append("Sequence includes a possible base/indecision before control confirmation")

    # Entry is at the confirming close in this first implementation. Pullback entry
    # is deliberately not fabricated: the notes say timing is context-dependent and
    # the exact pullback decision rules are still open.
    entry = float(confirm["close"])
    if side == "BUY":
        stop = min(float(c["low"]) for c in m1[sweep_index: m1.index(confirm) + 1])
        risk = entry - stop
        target_levels = [x for x in ref_highs if x > entry]
        target = min(target_levels) if target_levels else None
    else:
        stop = max(float(c["high"]) for c in m1[sweep_index: m1.index(confirm) + 1])
        risk = stop - entry
        target_levels = [x for x in ref_lows if x < entry]
        target = max(target_levels) if target_levels else None
    if risk <= 0:
        return Analysis(symbol, "NO_TRADE", side, "risk", tuple(evidence), tuple(missing + ["Structural stop does not produce positive risk"]))
    if target is None:
        return Analysis(symbol, "NO_TRADE", side, "target", tuple(evidence), tuple(missing + ["No next detected higher-timeframe reaction reference in the trade direction"]))
    reward = (target - entry) if side == "BUY" else (entry - target)
    rr = reward / risk
    if reward <= 0 or rr < 3.0:
        return Analysis(symbol, "NO_TRADE", side, "risk_reward", tuple(evidence), tuple(missing + [f"Next detected reaction area offers only 1:{rr:.2f}; minimum is 1:3"]))
    evidence.append(f"Structural stop at {stop:.5f}; next detected reaction reference at {target:.5f}; planned R:R 1:{rr:.2f}")
    evidence.append("Entry-at-close is provisional; context-dependent pullback comparison is not yet implemented")
    candidate = Candidate(
        symbol=symbol,
        side=side,
        entry=entry,
        stop_loss=stop,
        take_profit=target,
        risk_reward=rr,
        candle_epoch=int(confirm["epoch"]),
        explanation=" ".join(evidence) + " Research candidate only; the automated swing/zone and base detectors are provisional.",
        invalidation=(f"Setup invalid if price trades below {stop:.5f}." if side == "BUY" else f"Setup invalid if price trades above {stop:.5f}."),
        evidence=tuple(evidence),
        entry_style="decisive_close",
        target_reference="nearest detected higher-timeframe swing in trade direction",
    )
    return Analysis(symbol, "CANDIDATE", side, "risk_approved_candidate", tuple(evidence), tuple(missing), candidate)


def detect_candidate(
    symbol: str,
    candles_1h: list[dict[str, Any]],
    candles_15m: list[dict[str, Any]],
    candles_5m: list[dict[str, Any]],
    candles_1m: list[dict[str, Any]],
) -> Candidate | None:
    """Compatibility wrapper for the monitoring worker."""
    return analyze_setup(symbol, candles_1h, candles_15m, candles_5m, candles_1m).candidate
