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

import os

from dataclasses import dataclass, field
from statistics import median
from typing import Any, Literal

Side = Literal["BUY", "SELL"]

# Provisional, user-approved-for-testing thresholds (review after replay/paper results).
# A sweep may trade beyond a 15M swing level by up to this multiple of the median 15M range.
SWEEP_MAX_DEPTH_MULT = 0.75
# The sweep candle may sit up to this many completed 5M candles before the latest one.
SWEEP_LOOKBACK = 10
# A live signal must confirm on the latest completed 5M candle; older closes are stale.
CONFIRM_MAX_AGE = 1
# Dominance path (notes v1.3: "two or three consecutive closes in the same direction with
# strong bodies"): after the sweep, N consecutive closes in the trade direction, healthy bodies,
# finishing beyond the sweep candle's extreme. Provisional thresholds.
# Reaction-area ranking: a swing counts as significant when price reacts away from it
# by >= SIG_REACTION_MULT x the supplied timeframe-specific median range within the next
# SIG_REACTION_LOOKAHEAD candles, or when it is touched at least twice (equal highs/lows).
SIG_REACTION_MULT = 1.0
SIG_REACTION_LOOKAHEAD = 4
# "significant" (default) targets the nearest significant 5M/15M area; "nearest" uses any detected swing.
TARGET_MODE = os.getenv("TARGET_MODE", "significant").lower()
# Retest (pullback) entries: if entering at the confirming close fails 1:3, a limit order at the
# retest of the broken level may still qualify. Fill is NOT guaranteed; measure fill rates in replay.
PULLBACK_ENABLED = os.getenv("PULLBACK_ENABLED", "false").lower() == "true"
MIN_RR = 3.0
# A stop closer than this multiple of the median 5M range is inside normal noise: reject (R:R would be meaningless).
MIN_RISK_MULT = 0.5
# Assumed all-in spread in price units, used to shrink reward and widen risk. These are
# starting estimates, not measured Deriv values: override with ASSUMED_SPREADS="frxEURUSD=0.00012,...".
_DEFAULT_SPREADS = {"frxEURUSD": 0.00012, "frxGBPUSD": 0.00015, "frxXAUUSD": 0.35, "cryBTCUSD": 15.0}


def _load_spreads() -> dict[str, float]:
    spreads = dict(_DEFAULT_SPREADS)
    for part in os.getenv("ASSUMED_SPREADS", "").split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            try:
                spreads[k.strip()] = float(v)
            except ValueError:
                pass
    return spreads


ASSUMED_SPREADS: dict[str, float] = _load_spreads()
DOMINANCE_CLOSES = 3
DOMINANCE_MIN_MEAN_BODY = 0.45   # mean body/range of the streak candles
DOMINANCE_MIN_BODY = 0.20        # no single streak candle may be a doji-like sliver


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
    sweep_epoch: int = 0
    target_reference: str = "next detected reaction area"
    assumed_spread: float = 0.0


@dataclass(frozen=True)
class Analysis:
    symbol: str
    status: str
    side: str | None
    stage: str
    evidence: tuple[str, ...]
    missing: tuple[str, ...]
    candidate: Candidate | None = None
    details: dict[str, Any] = field(default_factory=dict)


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


def _structure_bias(candles: list[dict[str, Any]]) -> str | None:
    """Infer broad structure from confirmed swing progression, not candle colours.

    This is a conservative OHLC proxy: bullish requires both higher swing highs and
    higher swing lows; bearish requires both lower swing highs and lower swing lows.
    Mixed structure returns None and must not be described as a confirmed trend.
    """
    highs, lows = _swing_points(candles)
    if len(highs) < 2 or len(lows) < 2:
        return None
    high_progress = highs[-1][1] - highs[-2][1]
    low_progress = lows[-1][1] - lows[-2][1]
    if high_progress > 0 and low_progress > 0:
        return "bullish"
    if high_progress < 0 and low_progress < 0:
        return "bearish"
    return None


def _strong_counter_bias_confirmation(
    side: Side,
    sweep: dict[str, Any],
    candles: list[dict[str, Any]],
) -> tuple[bool, str]:
    """Require three strong directional closes and a break beyond the sweep candle.

    This stricter gate is only used when a setup opposes clear 15M dominance.
    Thresholds are provisional research settings, not validated performance claims.
    """
    if len(candles) < 3:
        return False, "Counter-bias setup requires three completed confirmation candles"
    streak = candles[-3:]
    closes = [float(c["close"]) for c in streak]
    for i, candle in enumerate(streak):
        o, h, low, close = (float(candle[k]) for k in ("open", "high", "low", "close"))
        candle_range = h - low
        body_ratio = abs(close - o) / candle_range if candle_range > 0 else 0.0
        directional = close < o if side == "SELL" else close > o
        if not directional:
            return False, "Counter-bias confirmation contains a candle without a directional body"
        if body_ratio < DOMINANCE_MIN_BODY:
            return False, "Counter-bias confirmation contains a doji-like weak body"
        if i > 0 and not (closes[i] < closes[i - 1] if side == "SELL" else closes[i] > closes[i - 1]):
            return False, "Counter-bias confirmation lacks consecutive close-to-close progress"
    mean_body_ratio = sum(
        abs(float(c["close"]) - float(c["open"])) /
        max(float(c["high"]) - float(c["low"]), 1e-12)
        for c in streak
    ) / 3
    if mean_body_ratio < DOMINANCE_MIN_MEAN_BODY:
        return False, "Counter-bias confirmation bodies are not strong enough on average"
    sweep_boundary = float(sweep["low"]) if side == "SELL" else float(sweep["high"])
    final_close = closes[-1]
    breaks_sweep = final_close < sweep_boundary if side == "SELL" else final_close > sweep_boundary
    if not breaks_sweep:
        boundary_name = "sweep-candle low" if side == "SELL" else "sweep-candle high"
        return False, f"Counter-bias confirmation has not closed beyond the {boundary_name}"
    return True, "Three strong directional closes and a close beyond the sweep-candle boundary"


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


def _swing_points(candles: list[dict[str, Any]], wing: int = 2) -> tuple[list[tuple[int, float]], list[tuple[int, float]]]:
    """Swing highs/lows as (index, price). Equal highs/lows count once (first occurrence)."""
    highs: list[tuple[int, float]] = []
    lows: list[tuple[int, float]] = []
    for i in range(wing, len(candles) - wing):
        hi, lo = float(candles[i]["high"]), float(candles[i]["low"])
        left_h = [float(c["high"]) for c in candles[i - wing:i]]
        right_h = [float(c["high"]) for c in candles[i + 1:i + wing + 1]]
        left_l = [float(c["low"]) for c in candles[i - wing:i]]
        right_l = [float(c["low"]) for c in candles[i + 1:i + wing + 1]]
        if hi > max(left_h) and hi >= max(right_h):
            highs.append((i, hi))
        if lo < min(left_l) and lo <= min(right_l):
            lows.append((i, lo))
    return highs, lows


def _latest_unambiguous_sweep(
    possible: list[tuple[int, Side, dict[str, Any], float]],
) -> tuple[tuple[int, Side, dict[str, Any], float] | None, str | None]:
    """Select the latest sweep, refusing a same-candle two-sided sweep."""
    if not possible:
        return None, None
    latest_idx = max(item[0] for item in possible)
    latest = [item for item in possible if item[0] == latest_idx]
    if len({item[1] for item in latest}) > 1:
        return None, "ambiguous_double_sweep"
    return max(latest, key=lambda item: item[0]), None


def _reaction_areas(candles: list[dict[str, Any]], tolerance: float, median_range: float):
    """Rank 15M swings by how much price actually reacted from them (significant vs minor)."""
    highs, lows = _swing_points(candles)

    def build(points: list[tuple[int, float]], kind: str) -> list[dict[str, Any]]:
        areas = []
        for i, level in points:
            touches = sum(1 for _, other in points if abs(other - level) <= tolerance)
            nxt = candles[i + 1:i + 1 + SIG_REACTION_LOOKAHEAD]
            if not nxt:
                reaction = 0.0
            elif kind == "high":
                reaction = level - min(float(c["low"]) for c in nxt)
            else:
                reaction = max(float(c["high"]) for c in nxt) - level
            areas.append({"level": level, "touches": touches, "reaction": reaction,
                          "significant": touches >= 2 or reaction >= SIG_REACTION_MULT * median_range})
        return areas

    return build(highs, "high"), build(lows, "low")


def _select_target_area(
    side: str,
    entry: float,
    areas_5m: list[dict[str, Any]],
    areas_15m: list[dict[str, Any]],
    target_mode: str = "significant",
) -> dict[str, Any] | None:
    """Choose the nearest eligible reaction/liquidity area beyond entry.

    The 5M areas give the strategy a nearby intraday target option; 15M areas
    retain the broader structure context. In significant mode, a level must
    show a meaningful reaction or repeated touches on its own timeframe.
    """
    candidates: list[dict[str, Any]] = []
    for timeframe, areas in (("5M", areas_5m), ("15M", areas_15m)):
        for area in areas:
            if target_mode != "nearest" and not area.get("significant", False):
                continue
            level = float(area["level"])
            is_ahead = level > entry if side == "BUY" else level < entry
            if not is_ahead:
                continue
            candidate = dict(area)
            candidate["timeframe"] = timeframe
            candidates.append(candidate)
    if not candidates:
        return None
    # Nearest valid target first; at equal prices prefer the higher-timeframe level.
    return min(candidates, key=lambda a: (abs(float(a["level"]) - entry), 0 if a["timeframe"] == "15M" else 1))


def _plan_entry(side: str, market_entry: float, stop: float, target: float, retest: float | None,
                retest_filled: bool, spread: float, min_rr: float = MIN_RR, pullback: bool = True) -> dict[str, Any]:
    """Choose market-at-close or retest-limit entry; R:R is net of the assumed spread."""
    def rr(entry: float) -> float:
        risk = abs(entry - stop) + spread
        reward = ((target - entry) if side == "BUY" else (entry - target)) - spread
        return reward / risk if risk > 0 and reward > 0 else 0.0

    rr_market = rr(market_entry)
    plan: dict[str, Any] = {"style": None, "entry": market_entry, "rr": rr_market, "rr_market": rr_market, "rr_pullback": None}
    if rr_market >= min_rr:
        plan["style"] = "market"
        return plan
    if pullback and retest is not None and not retest_filled:
        valid = (stop < retest < market_entry) if side == "BUY" else (market_entry < retest < stop)
        if valid:
            rr_pb = rr(retest)
            plan["rr_pullback"] = rr_pb
            if rr_pb >= min_rr:
                plan.update(style="pullback_limit", entry=retest, rr=rr_pb)
    return plan


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


def _dominance_confirm(side: str, sweep: dict[str, Any], after_sweep: list[dict[str, Any]]) -> dict[str, Any] | None:
    """First candle completing a run of consecutive closes in the trade direction after the sweep.

    Close-to-close (not candle colour), starting from the sweep candle's close; the run needs
    healthy bodies and must finish beyond the sweep candle's extreme in the trade direction.
    """
    prev_close = float(sweep["close"])
    streak: list[dict[str, Any]] = []
    for c in after_sweep:
        close = float(c["close"])
        moved = close > prev_close if side == "BUY" else close < prev_close
        streak = streak + [c] if moved else []
        prev_close = close
        if len(streak) >= DOMINANCE_CLOSES:
            last = streak[-DOMINANCE_CLOSES:]
            ratios = []
            for k in last:
                rng = float(k["high"]) - float(k["low"])
                ratios.append(abs(float(k["close"]) - float(k["open"])) / rng if rng > 0 else 0.0)
            beyond = close > float(sweep["high"]) if side == "BUY" else close < float(sweep["low"])
            if beyond and sum(ratios) / len(ratios) >= DOMINANCE_MIN_MEAN_BODY and min(ratios) >= DOMINANCE_MIN_BODY:
                return c
    return None


def analyze_setup(
    symbol: str,
    candles_15m: list[dict[str, Any]],
    candles_5m: list[dict[str, Any]],
    candles_1m: list[dict[str, Any]] | None = None,
    opts: dict[str, Any] | None = None,
) -> Analysis:
    """Evaluate 15M context and 5M execution (one-way entry at confirming close).

    1M is disabled. Entry is the 5M confirmation close. No limit / retest wait.

    ``opts``: target_mode, pullback, min_rr, spread.
    """
    opts = opts or {}
    target_mode = str(opts.get("target_mode", TARGET_MODE))
    pullback_on = bool(opts.get("pullback", PULLBACK_ENABLED))
    min_rr = float(opts.get("min_rr", MIN_RR))
    # 15M context + 5M execution only (1M disabled by user request).
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
    m1 = data.get("1M") or []

    m15_dom = _dominance(m15, 3)
    if m15_dom:
        evidence.append(f"15M close-to-close dominance: {m15_dom}")
    else:
        evidence.append("15M close-to-close dominance is mixed/unclear")
    structural_bias = _structure_bias(m15)
    context_bias = structural_bias or m15_dom
    if structural_bias:
        evidence.append(f"15M swing structure: {structural_bias} (higher/lower highs and lows)")
    else:
        evidence.append("15M swing structure is mixed/unclear; close-to-close progress is fallback context")
    # Use confirmed 15M swing references; 1H is intentionally removed.
    ref_highs, ref_lows = _swing_levels(m15[-100:])
    ref_highs = sorted(set(ref_highs))
    ref_lows = sorted(set(ref_lows))
    recent_15m_ranges = [float(c["high"]) - float(c["low"]) for c in m15[-20:]]
    tolerance = median(recent_15m_ranges) * 0.15 if recent_15m_ranges else 0.0
    median_15m_range = median(recent_15m_ranges) if recent_15m_ranges else 0.0
    areas_high, areas_low = _reaction_areas(m15[-100:], tolerance, median_15m_range)
    if tolerance <= 0:
        return Analysis(symbol, "NO_TRADE", None, "location", tuple(evidence), ("Could not estimate a usable reaction-area tolerance",))

    # 5M is the approach/context layer: record weakening progress or conflict.
    m5_dom = _dominance(m5, 3)
    if m5_dom:
        evidence.append(f"5M close-to-close dominance: {m5_dom}")
    else:
        evidence.append("5M dominance is mixed/unclear; inspect the candle sequence at the area")
    # Timeframe disagreement is recorded as evidence, not used as a premature hard
    # rejection. The setup-specific counter-bias gate runs only after a sweep is found.
    if m5_dom and context_bias and m5_dom != context_bias:
        evidence.append(
            f"5M close-to-close progress ({m5_dom}) conflicts with 15M context ({context_bias}); "
            "do not reject automatically—classify any setup against context and apply the appropriate confirmation gate"
        )

    # Look for either a high sweep/rejection or a low sweep/reclaim at a meaningful
    # higher-timeframe reference. Context helps rank the setup; it does not dictate
    # direction by itself. A sweep alone still cannot produce a candidate.
    side: Side | None = None
    sweep: dict[str, Any] | None = None
    swept_level: float | None = None
    max_depth = median(recent_15m_ranges) * SWEEP_MAX_DEPTH_MULT
    possible: list[tuple[int, Side, dict[str, Any], float]] = []
    first = max(8, len(m5) - 1 - SWEEP_LOOKBACK)
    for i in range(first, len(m5) - 2):  # need at least 2 completed candles after the sweep (the two-close rule)
        candle = m5[i]
        low, high, close = float(candle["low"]), float(candle["high"]), float(candle["close"])
        swept_lows = [lv for lv in ref_lows if low < lv <= low + max_depth and close > lv]
        swept_highs = [lv for lv in ref_highs if high > lv >= high - max_depth and close < lv]
        if swept_lows:
            possible.append((i, "BUY", candle, max(swept_lows)))
        if swept_highs:
            possible.append((i, "SELL", candle, min(swept_highs)))
    selected_sweep, sweep_issue = _latest_unambiguous_sweep(possible)
    if sweep_issue == "ambiguous_double_sweep":
        return Analysis(symbol, "NO_TRADE", None, "location_or_sweep", tuple(evidence), (
            "Ambiguous double-sided sweep in the same 5M candle; OHLC cannot establish which boundary was taken first",
        ))
    if selected_sweep is not None:
        _, side, sweep, swept_level = selected_sweep
        if context_bias and ((context_bias == "bullish" and side == "SELL") or (context_bias == "bearish" and side == "BUY")):
            evidence.append(f"{side} sweep runs against current 15M context; require especially clear confirmation")

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

    after_sweep = m5[sweep_index + 1:]
    if len(after_sweep) < 2:
        return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), ("Need at least two completed candles after the sweep to confirm control",))

    # Normal setups need two directional body closes; counter-bias setups must find
    # a full three-candle strong sequence that also breaks the sweep-candle boundary.
    counter_bias_required = bool(
        context_bias and
        ((context_bias == "bullish" and side == "SELL") or
         (context_bias == "bearish" and side == "BUY"))
    )
    confirm: dict[str, Any] | None = None
    count = 0
    for j in range(1, len(after_sweep)):
        prev, current = after_sweep[j - 1], after_sweep[j]
        po, pc = float(prev["open"]), float(prev["close"])
        co, cc = float(current["open"]), float(current["close"])
        valid = (pc < po and cc < co and cc < pc) if side == "SELL" else (pc > po and cc > co and cc > pc)
        if not valid:
            continue
        third = after_sweep[j + 1] if j + 1 < len(after_sweep) else None
        third_matches = False
        if third is not None:
            to, tc = float(third["open"]), float(third["close"])
            third_matches = (tc < to and tc < cc) if side == "SELL" else (tc > to and tc > cc)
        if counter_bias_required:
            if not third_matches:
                continue
            strong_ok, _ = _strong_counter_bias_confirmation(side, sweep, after_sweep[j - 1:j + 2])
            if not strong_ok:
                continue
            confirm, count = third, 3
            break
        confirm, count = current, 2
        if third_matches:
            confirm, count = third, 3
        break
    if confirm is None:
        return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), ("No two consecutive directional body closes with close-to-close progress after the sweep",))
    path = "dominance_closes"
    reaction_high = reaction_low = None
    counter_bias = bool(
        context_bias and
        ((context_bias == "bullish" and side == "SELL") or
         (context_bias == "bearish" and side == "BUY"))
    )
    if counter_bias:
        confirm_index_for_gate = next(
            (i for i, candle in enumerate(m5) if int(candle["epoch"]) == int(confirm["epoch"])),
            None,
        )
        if confirm_index_for_gate is None:
            return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), (
                "Could not locate counter-bias confirmation candles in ordered data",
            ))
        confirmation_streak = m5[max(sweep_index + 1, confirm_index_for_gate - 2):confirm_index_for_gate + 1]
        strong_ok, strong_reason = _strong_counter_bias_confirmation(side, sweep, confirmation_streak)
        if count < 3 or not strong_ok:
            evidence.append("Counter-bias SELL/BUY requires stricter confirmation because 15M dominance points the other way")
            return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), (
                f"Counter-bias confirmation rejected: {strong_reason if not strong_ok else 'only two consecutive directional closes; three are required'}",
            ))
        evidence.append(f"Counter-bias gate passed: {strong_reason}")
    evidence.append(f"{count} consecutive {'bearish' if side == 'SELL' else 'bullish'} body closes with directional close-to-close progress confirmed control; final close {float(confirm['close']):.5f}")
    confirm_index = next((i for i, c in enumerate(m5) if int(c["epoch"]) == int(confirm["epoch"])), None)
    if confirm_index is None:
        return Analysis(symbol, "NO_TRADE", side, "control_confirmation", tuple(evidence), ("Could not locate confirmation candle in ordered data",))
    if confirm_index < len(m5) - CONFIRM_MAX_AGE:
        return Analysis(symbol, "NO_TRADE", side, "stale_confirmation", tuple(evidence), (f"Confirmation is older than {CONFIRM_MAX_AGE} completed 5M candles; entry would be stale",))
    # One-way entry at the 5M confirming close (no 1M, no limit/retest wait).
    entry = float(confirm["close"])
    evidence.append(
        f"5M execution at confirming close {entry:.5f} "
        f"({count} consecutive directional body closes with close-to-close progress)"
    )
    configured_spread = opts.get("spread", ASSUMED_SPREADS.get(symbol))
    if configured_spread is None:
        return Analysis(symbol, "NO_TRADE", side, "cost_model", tuple(evidence), tuple(missing + [
            f"No assumed spread configured for {symbol}; refusing to report a cost-adjusted 1:{min_rr:g} setup using zero costs",
            "Configure a measured or explicitly provisional ASSUMED_SPREADS value before evaluating this symbol",
        ]), None, {"confirm_epoch": int(confirm["epoch"]), "symbol": symbol, "spread_missing": True})
    spread = float(configured_spread)
    if spread < 0:
        return Analysis(symbol, "NO_TRADE", side, "cost_model", tuple(evidence), tuple(missing + ["Assumed spread cannot be negative"]))
    if side == "BUY":
        # Structural invalidation stays beyond the swept low.
        stop = min(float(sweep["low"]), min(float(c["low"]) for c in m5[sweep_index: confirm_index + 1]))
        retest = float(sweep["high"])
        retest_filled = any(float(c["low"]) <= retest for c in m5[confirm_index + 1:])
    else:
        # Structural invalidation stays beyond the swept high.
        stop = max(float(sweep["high"]), max(float(c["high"]) for c in m5[sweep_index: confirm_index + 1]))
        retest = float(sweep["low"])
        retest_filled = any(float(c["high"]) >= retest for c in m5[confirm_index + 1:])

    # Add nearby 5M reaction/liquidity areas to the existing 15M structure map.
    # Use a slightly more sensitive threshold on 5M so clear intraday reactions
    # are not ignored merely because they are smaller than a 15M candle range.
    ranges_5m = [float(c["high"]) - float(c["low"]) for c in m5[-30:]]
    median_5m_range = median(ranges_5m) if ranges_5m else 0.0
    if median_5m_range > 0:
        tolerance_5m = median_5m_range * 0.15
        areas_5m_high, areas_5m_low = _reaction_areas(m5[-100:], tolerance_5m, median_5m_range * 0.75)
    else:
        areas_5m_high, areas_5m_low = [], []
    target_area = _select_target_area(
        side,
        entry,
        areas_5m_high if side == "BUY" else areas_5m_low,
        areas_high if side == "BUY" else areas_low,
        target_mode,
    )
    risk = (entry - stop) if side == "BUY" else (stop - entry)
    if risk <= 0:
        return Analysis(symbol, "NO_TRADE", side, "risk", tuple(evidence), tuple(missing + ["Structural stop does not produce positive risk"]))
    min_risk = median_5m_range * MIN_RISK_MULT if median_5m_range > 0 else 0.0
    if risk < min_risk:
        return Analysis(symbol, "NO_TRADE", side, "risk", tuple(evidence), tuple(missing + [f"Stop is only {risk:g} away, inside normal 5M noise (minimum {min_risk:g} = {MIN_RISK_MULT:g}x median 5M range); R:R would be meaningless"]), None, {"confirm_epoch": int(confirm["epoch"]), "risk": risk, "min_risk": min_risk})
    if target_area is None:
        kind = "significant 5M/15M reaction area" if target_mode != "nearest" else "5M/15M reaction reference"
        return Analysis(symbol, "NO_TRADE", side, "target", tuple(evidence), tuple(missing + [f"No {kind} ahead in the trade direction"]), None, {"confirm_epoch": int(confirm["epoch"]), "no_target": True})
    target = float(target_area["level"])
    plan = _plan_entry(side, entry, stop, target, retest, retest_filled, spread, min_rr, False)  # one-way only: no limit/retest wait
    if plan["style"] is None:
        msg = f"Next reaction area offers only 1:{plan['rr_market']:.2f} at the confirming close (net of assumed spread {spread:g}); minimum is 1:{min_rr:g}"
        if plan["rr_pullback"] is not None:
            msg += f"; a retest entry would offer 1:{plan['rr_pullback']:.2f}"
        return Analysis(symbol, "NO_TRADE", side, "risk_reward", tuple(evidence), tuple(missing + [msg]), None, {"confirm_epoch": int(confirm["epoch"]), "rr_market": plan["rr_market"], "rr_pullback": plan["rr_pullback"], "risk": risk, "side": side, "entry": entry, "stop": stop, "target": target, "sweep_epoch": int(sweep["epoch"]), "reward_to_target": abs(target - entry), "target_touches": target_area["touches"], "target_reaction": target_area["reaction"], "spread": spread})
    style = ("pullback_limit" if plan["style"] == "pullback_limit"
             else ("dominance_closes" if path == "dominance_closes" else "decisive_close"))
    final_entry = float(plan["entry"])
    rr = float(plan["rr"])
    area_note = (
        f"{target_area['timeframe']} area, touched {target_area['touches']}x, "
        f"reaction {target_area['reaction']:.5f}"
        if target_mode != "nearest"
        else f"nearest {target_area['timeframe']} swing/liquidity reference"
    )
    evidence.append(f"Structural stop at {stop:.5f}; target = {'significant ' if target_mode != 'nearest' else ''}{target_area['timeframe']} reaction/liquidity area at {target:.5f} ({area_note}); planned R:R 1:{rr:.2f} net of assumed spread {spread:g}")
    if style == "pullback_limit":
        evidence.append(f"Market entry at {entry:.5f} only offers 1:{plan['rr_market']:.2f}; LIMIT idea at the retest of the broken level {final_entry:.5f} (may never fill)")
        invalidation = (f"Limit idea only. Cancel if price trades {'below' if side == 'BUY' else 'above'} {stop:.5f} before filling, "
                        "or if it moves away without retesting; do not chase.")
    else:
        evidence.append("Entry at the confirming close; a retest entry is not required")
        if plan["rr_pullback"] is not None:
            evidence.append(f"Alternative retest entry at {float(retest):.5f} would offer 1:{plan['rr_pullback']:.2f} (less risk, but may not fill)")
        invalidation = f"Setup invalid if price trades {'below' if side == 'BUY' else 'above'} {stop:.5f}."
    candidate = Candidate(
        symbol=symbol,
        side=side,
        entry=final_entry,
        stop_loss=stop,
        take_profit=target,
        risk_reward=rr,
        candle_epoch=int(confirm["epoch"]),
        explanation=" ".join(evidence) + " Research candidate only; the automated swing/zone and base detectors are provisional.",
        invalidation=invalidation,
        evidence=tuple(evidence),
        entry_style=style,
        sweep_epoch=int(sweep["epoch"]),
        target_reference=(f"nearest {'significant ' if target_mode != 'nearest' else ''}{target_area['timeframe']} reaction/liquidity area in trade direction"),
        assumed_spread=spread,
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
    candles_1m: list[dict[str, Any]] | None = None,
) -> Candidate | None:
    """Run the 15M context, 5M control, 1M execution strategy."""
    return analyze_setup(symbol, candles_15m, candles_5m, candles_1m).candidate
