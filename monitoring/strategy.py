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

# Provisional, user-approved-for-testing thresholds (review after replay/paper results).
# A sweep may trade beyond a 15M swing level by up to this multiple of the median 15M range.
SWEEP_MAX_DEPTH_MULT = 0.75
# The sweep candle may sit up to this many completed 5M candles before the latest one.
SWEEP_LOOKBACK = 10
# The confirming close must be one of the latest N completed 5M candles (fresh entry only).
CONFIRM_MAX_AGE = 2


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
        hi = float(candles[i]["high"])
        lo = float(candles[i]["low"])
        left_h = [float(c["high"]) for c in candles[i - wing:i]]
        right_h = [float(c["high"]) for c in candles[i + 1:i + wing + 1]]
        left_l = [float(c["low"]) for c in candles[i - wing:i]]
        right_l = [float(c["low"]) for c in candles[i + 1:i + wing + 1]]
        # Ties on the right are allowed so equal highs/lows (liquidity pools) still count once.
        if hi > max(left_h) and hi >= max(right_h):
            highs.append(hi)
        if lo < min(left_l) and lo <= min(right_l):
            lows.append(lo)
    return highs, lows


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
    candles_15m: list[dict[str, Any]],
    candles_5m: list[dict[str, Any]],
) -> Analysis:
    """Evaluate the setup using 15M context and 5M execution candles."""
    raw = {"15M": candles_15m, "5M": candles_5m}
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
    m15, m5 = data["15M"], data["5M"]

    m15_dom = _dominance(m15, 3)
    if m15_dom:
        evidence.append(f"15M close-to-close dominance: {m15_dom}")
    else:
        evidence.append("15M close-to-close dominance is mixed/unclear")
    context_bias = m15_dom
    # Use confirmed 15M swing references; 1H is intentionally removed.
    ref_highs, ref_lows = _swing_levels(m15[-100:])
    ref_highs = sorted(set(ref_highs))
    ref_lows = sorted(set(ref_lows))
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
    # Only apply the opposing-direction filter when 15M has a clear direction.
    # Previously, unclear 1H (None) made every clear 5M direction look opposed.
    # Unclear context is not the same as opposing context.
    if m5_dom and m15_dom and m5_dom != m15_dom:
        recent_5m = m5[-5:]
        if _dominance(recent_5m, 3) == m5_dom:
            return Analysis(symbol, "NO_TRADE", None, "approach", tuple(evidence), ("5M is still making clear progress against the 15M direction; no confirmed loss of that control",))

    # Look for either a high sweep/rejection or a low sweep/reclaim at a meaningful
    # higher-timeframe reference. Context helps rank the setup; it does not dictate
    # direction by itself. A sweep alone still cannot produce a candidate.
    side: Side | None = None
    sweep: dict[str, Any] | None = None
    swept_level: float | None = None
    max_depth = median(recent_15m_ranges) * SWEEP_MAX_DEPTH_MULT
    possible: list[tuple[int, Side, dict[str, Any], float]] = []
    first = max(8, len(m5) - 1 - SWEEP_LOOKBACK)
    for i in range(first, len(m5) - 4):  # need 3 reaction candles + a later confirming close
        candle = m5[i]
        low, high, close = float(candle["low"]), float(candle["high"]), float(candle["close"])
        swept_lows = [lv for lv in ref_lows if low < lv <= low + max_depth and close > lv]
        swept_highs = [lv for lv in ref_highs if high > lv >= high - max_depth and close < lv]
        if swept_lows:
            possible.append((i, "BUY", candle, max(swept_lows)))
        if swept_highs:
            possible.append((i, "SELL", candle, min(swept_highs)))
    if possible:
        # Prefer the latest sweep. If context conflicts with it, keep the setup for
        # confirmation analysis but record that extra evidence is required.
        _, side, sweep, swept_level = possible[-1]
        if context_bias and ((context_bias == "bullish" and side == "SELL") or (context_bias == "bearish" and side == "BUY")):
            evidence.append(f"{side} sweep runs against current dominant close-to-close bias; require especially clear confirmation")

    if side is None or sweep is None or swept_level is None:
        return Analysis(symbol, "NO_TRADE", None, "location_or_sweep", tuple(evidence), (
            "No recent 5M sweep-and-reclaim was found at a detected 15M swing reference",
            "A swing reference is only a proxy for a meaningful area; review the chart context",
        ))
    evidence.append(f"5M swept and reclaimed detected higher-timeframe reference {swept_level:.5f}")
    evidence.append("Sweep treated as context only; waiting for post-sweep rejection/response and a decisive close")

    sweep_index = next((i for i, c in enumerate(m5) if int(c["epoch"]) == int(sweep["epoch"])), None)
    if sweep_index is None or sweep_index < 8 or sweep_index + 1 >= len(m5):
        return Analysis(symbol, "NO_TRADE", side, "post_sweep_reaction", tuple(evidence), ("Insufficient candles before/after sweep to assess the reaction",))

    before_cluster = m5[max(0, sweep_index - 3):sweep_index]
    after_sweep = m5[sweep_index + 1:]
    if len(after_sweep) < 2:
        return Analysis(symbol, "NO_TRADE", side, "post_sweep_reaction", tuple(evidence), ("Need completed candles after the sweep to assess rejection/indecision and the response",))

    # The strategy notes describe indecision/rejection AFTER the false sweep.
    # This detector is still a proxy: it looks for a compact/alternating reaction
    # after the sweep, then requires a later close beyond that reaction's range.
    base, base_note = _indecision_or_base(before_cluster + [sweep] + after_sweep[:3], count=3)
    evidence.append(base_note)
    if not base:
        return Analysis(symbol, "NO_TRADE", side, "post_sweep_reaction", tuple(evidence), ("No clear post-sweep indecision/base detected by the provisional heuristic; inspect rejection manually",))

    reaction = after_sweep[:3]
    reaction_high = max(float(c["high"]) for c in reaction)
    reaction_low = min(float(c["low"]) for c in reaction)
    confirm: dict[str, Any] | None = None
    for c in after_sweep[3:]:
        if side == "BUY" and float(c["close"]) > reaction_high:
            confirm = c
            break
        if side == "SELL" and float(c["close"]) < reaction_low:
            confirm = c
            break
    if confirm is None:
        return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), ("No later completed close beyond the post-sweep reaction range; sweep and indecision alone are not entry signals",))
    evidence.append(f"Post-sweep reaction formed a possible base; later candle closed beyond its range at {float(confirm['close']):.5f}")
    confirm_index = next((i for i, c in enumerate(m5) if int(c["epoch"]) == int(confirm["epoch"])), None)
    if confirm_index is None:
        return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), ("Could not locate confirmation candle in ordered data",))
    if confirm_index < len(m5) - CONFIRM_MAX_AGE:
        return Analysis(symbol, "NO_TRADE", side, "stale_confirmation", tuple(evidence), (f"Confirmation is older than {CONFIRM_MAX_AGE} completed 5M candles; entry would be stale",))
    # Entry is at the confirming close in this first implementation. Pullback entry
    # is deliberately not fabricated: the notes say timing is context-dependent and
    # the exact pullback decision rules are still open.
    entry = float(confirm["close"])
    if side == "BUY":
        stop = min(float(c["low"]) for c in m5[sweep_index: confirm_index + 1])
        risk = entry - stop
        target_levels = [x for x in ref_highs if x > entry]
        target = min(target_levels) if target_levels else None
    else:
        stop = max(float(c["high"]) for c in m5[sweep_index: confirm_index + 1])
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


def analyze_annotated_short(
    symbol: str,
    candles_15m: list[dict[str, Any]],
    candles_5m: list[dict[str, Any]],
    *,
    rejection_high: float,
    confirmation_high: float,
    confirmation_low: float,
    entry_reference: float,
    stop_reference: float,
    target_reference: float,
) -> Analysis:
    """Replay an explicitly annotated 5-minute short setup against candles.

    Unlike analyze_setup(), this function uses user-marked levels instead of
    pretending swing heuristics can infer the annotations. It is a replay helper,
    not a live signal generator. It checks the sequence around the marked levels;
    exact OHLC candles are required to validate timing.
    """
    raw = {"15M": candles_15m, "5M": candles_5m}
    data = {tf: _completed(cs) for tf, cs in raw.items()}
    missing: list[str] = []
    evidence: list[str] = []
    if any(len(data[tf]) < 20 for tf in data):
        return Analysis(symbol, "NO_TRADE", "SELL", "data_quality", (), ("Need at least 20 valid 15M and 5M candles for replay context",))
    data = {tf: cs[:-1] for tf, cs in data.items()}
    m15_dom = _dominance(data["15M"], 3)
    evidence.append(f"15M dominance: {m15_dom or 'unclear'}")
    if m15_dom not in (None, "bearish"):
        return Analysis(symbol, "NO_TRADE", "SELL", "higher_timeframe_context", tuple(evidence), ("15M dominance is bullish, so this annotated short needs a stronger reversal confirmation",))
    m5_dom = _dominance(data["5M"], 3)
    evidence.append(f"5M approach dominance: {m5_dom or 'mixed/unclear'}")
    candles = data["5M"]
    # Locate a completed 5-minute candle that trades above the marked rejection reference
    # and closes back below it. This is the observable sweep/rejection condition.
    sweep_i = None
    for i, c in enumerate(candles):
        if float(c["high"]) >= rejection_high and float(c["close"]) < rejection_high:
            sweep_i = i
    if sweep_i is None:
        return Analysis(symbol, "NO_TRADE", "SELL", "sweep_rejection", tuple(evidence), (f"No completed 5M candle tested {rejection_high:.3f} and closed back below it",))
    evidence.append(f"Rejection reference {rejection_high:.3f} tested and close returned below it")
    # Require later price action to enter the marked confirmation band and close
    # below its lower edge; a zone touch alone is not confirmation.
    confirm = None
    for c in candles[sweep_i + 1:]:
        if float(c["high"]) >= confirmation_low and float(c["low"]) <= confirmation_high:
            evidence.append(f"Price traded through marked confirmation band {confirmation_low:.3f}-{confirmation_high:.3f}")
        if float(c["close"]) < confirmation_low:
            confirm = c
            break
    if confirm is None:
        return Analysis(symbol, "NO_TRADE", "SELL", "seller_confirmation", tuple(evidence), ("No later completed close below the marked confirmation band",))
    entry = float(confirm["close"])
    stop = max(stop_reference, rejection_high)
    risk = stop - entry
    reward = entry - target_reference
    if risk <= 0 or reward <= 0:
        return Analysis(symbol, "NO_TRADE", "SELL", "risk", tuple(evidence), ("Annotated levels do not produce positive risk and reward",))
    rr = reward / risk
    evidence.append(f"Confirmation close {entry:.5f}; invalidation {stop:.5f}; target {target_reference:.5f}; planned R:R 1:{rr:.2f} before costs")
    if rr < 3:
        return Analysis(symbol, "NO_TRADE", "SELL", "risk_reward", tuple(evidence), ("Annotated levels do not meet minimum planned 1:3 R:R before costs",))
    candidate = Candidate(symbol, "SELL", entry, stop, target_reference, rr, int(confirm["epoch"]),
        "Annotated short replay candidate; based on user-supplied rejection/confirmation/target levels. Research only.",
        f"Setup invalid if price trades above {stop:.5f}.", tuple(evidence), "decisive_close",
        "user-annotated target")
    return Analysis(symbol, "CANDIDATE", "SELL", "annotated_replay_candidate", tuple(evidence), tuple(missing), candidate)


def detect_candidate(
    symbol: str,
    candles_15m: list[dict[str, Any]],
    candles_5m: list[dict[str, Any]],
) -> Candidate | None:
    """Run the 15M/5M strategy; 1H and 1M are not required."""
    return analyze_setup(symbol, candles_15m, candles_5m).candidate
