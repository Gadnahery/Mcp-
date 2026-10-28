"""On-demand historical replay of the strategy engine using live Deriv candles."""
from __future__ import annotations

from collections import Counter
from types import SimpleNamespace
from typing import Any

from .strategy import analyze_setup


def _simulate(c: Any, future: list[dict[str, Any]], max_wait: int = 12) -> tuple[str, float | None]:
    """Outcome after a signal. Retest limits must fill first (within max_wait candles).

    Same-candle stop+target is scored as a stop (worst case). Returns (outcome, R multiple).
    """
    buy = c.side == "BUY"
    filled = c.entry_style != "pullback_limit"
    risk = abs(c.entry - c.stop_loss)
    for n, f in enumerate(future):
        hit_stop = f["low"] <= c.stop_loss if buy else f["high"] >= c.stop_loss
        hit_tp = f["high"] >= c.take_profit if buy else f["low"] <= c.take_profit
        if not filled:
            if hit_stop:
                return "cancelled (stop level hit before fill)", None
            if n >= max_wait:
                return "unfilled", None
            if (f["low"] <= c.entry) if buy else (f["high"] >= c.entry):
                filled = True
                if hit_tp:  # filled and ran to target within the same candle: unknowable order
                    return "stop (fill candle also hit target; worst case)", -1.0
                continue
            continue
        if hit_stop and hit_tp:
            return "stop (same candle; worst case)", -1.0
        if hit_stop:
            return "stop", -1.0
        if hit_tp:
            return "target", round(c.risk_reward, 2)
    return ("open" if filled else "unfilled"), None


def run_replay(
    symbol: str,
    m15: list[dict[str, Any]],
    m5: list[dict[str, Any]],
    m1: list[dict[str, Any]] | None = None,
    warmup: int = 60,
    opts: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Walk 5M candle-by-candle and collect gate tally + candidates with outcomes."""
    tally: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []
    seen: set[int] = set()
    last_analysis: dict[str, Any] | None = None
    near_misses: dict[int, dict[str, Any]] = {}
    first_m1 = min((int(c["epoch"]) for c in (m1 or [])), default=None)
    skipped_no_1m = 0
    evaluated = 0

    if len(m5) <= warmup + 1:
        return {
            "symbol": symbol,
            "error": f"Not enough 5M candles ({len(m5)}); need > {warmup + 1}",
            "tally": {},
            "candidates": [],
            "bars_evaluated": 0,
        }

    for idx in range(warmup, len(m5) - 1):
        now_epoch = int(m5[idx]["epoch"]) + 300  # this 5M candle just closed
        if first_m1 is not None and int(m5[idx]["epoch"]) < first_m1 + 600:
            skipped_no_1m += 1  # 1M history does not reach this far back: cannot judge fairly
            continue
        evaluated += 1
        view5 = [c for c in m5[: idx + 2] if int(c["epoch"]) <= now_epoch]
        view15 = [c for c in m15 if int(c["epoch"]) <= now_epoch]
        view1 = [c for c in (m1 or []) if int(c["epoch"]) <= now_epoch] or None
        result = analyze_setup(symbol, view15, view5, view1, opts)
        stage_key = "CANDIDATE" if result.status == "CANDIDATE" else result.stage
        tally[stage_key] += 1
        last_analysis = {
            "status": result.status,
            "side": result.side,
            "stage": result.stage,
            "missing": list(result.missing)[:4],
            "evidence": list(result.evidence)[-4:],
            "at_epoch": now_epoch,
        }
        det = result.details or {}
        if result.stage in ("risk_reward", "target") and det.get("confirm_epoch") is not None:
            nm_key = (det.get("sweep_epoch"), result.side) if det.get("sweep_epoch") else int(det["confirm_epoch"])
            if nm_key not in near_misses:
                entry_ = {
                    "side": result.side, "stage": result.stage,
                    "rr_market": det.get("rr_market"), "rr_pullback": det.get("rr_pullback"),
                    "touches": det.get("target_touches"),
                }
                if det.get("entry") is not None and det.get("stop") is not None and det.get("target") is not None:
                    pseudo = SimpleNamespace(side=result.side, entry=det["entry"], stop_loss=det["stop"],
                                             take_profit=det["target"], risk_reward=det.get("rr_market") or 0.0,
                                             entry_style="market")
                    out, r_ = _simulate(pseudo, m5[idx + 1:])
                    entry_["if_taken"] = out
                    entry_["if_taken_r"] = r_
                near_misses[nm_key] = entry_
        key = (result.candidate.sweep_epoch, result.candidate.side) if result.candidate else None
        if result.candidate and key not in seen:
            seen.add(key)
            c = result.candidate
            outcome, r_mult = _simulate(c, m5[idx + 1 :])
            candidates.append({
                "side": c.side,
                "entry": c.entry,
                "stop": c.stop_loss,
                "target": c.take_profit,
                "rr": round(c.risk_reward, 2),
                "epoch": c.candle_epoch,
                "outcome": outcome,
                "r": r_mult,
                "style": c.entry_style,
                "invalidation": c.invalidation,
                "evidence": list(c.evidence)[-3:],
            })

    done = [c for c in candidates if c.get("r") is not None]
    summary = {
        "targets": sum(1 for c in candidates if c["outcome"] == "target"),
        "stops": sum(1 for c in candidates if str(c["outcome"]).startswith("stop")),
        "open": sum(1 for c in candidates if c["outcome"] == "open"),
        "unfilled_or_cancelled": sum(1 for c in candidates if c["outcome"].startswith(("unfilled", "cancelled"))),
        "net_r": round(sum(c["r"] for c in done), 2),
    }
    best = [max(x for x in (m["rr_market"], m["rr_pullback"]) if x is not None) for m in near_misses.values()
            if m.get("rr_market") is not None]
    near = sorted(best, reverse=True)
    return {
        "symbol": symbol,
        "opts": opts or {},
        "summary": summary,
        "near_misses": {
            "setups_that_failed_rr_or_target": len(near_misses),
            "best_rr_values": [round(x, 2) for x in near[:8]],
            "would_pass_at_2.0": sum(1 for x in near if x >= 2.0),
            "would_pass_at_2.5": sum(1 for x in near if x >= 2.5),
            "no_significant_target": sum(1 for m in near_misses.values() if m["stage"] == "target"),
            "if_taken_at_market": {
                "targets": sum(1 for m in near_misses.values() if m.get("if_taken") == "target"),
                "stops": sum(1 for m in near_misses.values() if str(m.get("if_taken", "")).startswith("stop")),
                "open": sum(1 for m in near_misses.values() if m.get("if_taken") == "open"),
                "net_r": round(sum(m["if_taken_r"] for m in near_misses.values() if m.get("if_taken_r") is not None), 2),
            },
        },
        "bars_evaluated": evaluated if first_m1 is not None else max(0, len(m5) - warmup - 1),
        "bars_skipped_no_1m": skipped_no_1m,
        "m15_count": len(m15),
        "m5_count": len(m5),
        "tally": dict(tally.most_common()),
        "candidates": candidates,
        "last": last_analysis,
    }


def format_replay_report(result: dict[str, Any]) -> str:
    if result.get("error"):
        return f"Replay error for {result.get('symbol')}: {result['error']}"

    symbol = result["symbol"]
    lines = [
        f"📼 Replay · {symbol}",
        f"Bars evaluated: {result['bars_evaluated']} "
        f"(5M:{result['m5_count']} / 15M:{result['m15_count']})",
        "",
        "Where evaluations stopped (gate tally):",
    ]
    tally = result.get("tally") or {}
    if not tally:
        lines.append("  (no evaluations)")
    else:
        for stage, n in tally.items():
            lines.append(f"  {stage}: {n}")

    nm = result.get("near_misses") or {}
    if nm.get("setups_that_failed_rr_or_target"):
        lines.append("")
        lines.append(
            f"Setups found but rejected at R:R/target: {nm['setups_that_failed_rr_or_target']} "
            f"(no significant target: {nm.get('no_significant_target', 0)})"
        )
        lines.append(f"  best R:R seen: {nm.get('best_rr_values')}")
        lines.append(f"  would pass at 1:2.5: {nm.get('would_pass_at_2.5')} · at 1:2: {nm.get('would_pass_at_2.0')}")
        it = nm.get("if_taken_at_market") or {}
        lines.append(f"  if taken at market anyway (not recommended, just data): targets {it.get('targets')}, stops {it.get('stops')}, open {it.get('open')}, net {it.get('net_r')}R at their planned R:R")
    cands = result.get("candidates") or []
    lines.append("")
    if not cands:
        lines.append("No complete setups found in this window.")
        last = result.get("last") or {}
        if last:
            lines.append("")
            lines.append("Latest bar verdict:")
            lines.append(f"  {last.get('status')} {last.get('side') or ''} · stage={last.get('stage')}")
            for m in last.get("missing") or []:
                lines.append(f"  Invalid/why: {m}")
            for e in last.get("evidence") or []:
                lines.append(f"  • {e}")
    else:
        sm = result.get("summary") or {}
        lines.append(f"Setups found: {len(cands)} — targets {sm.get('targets')}, stops {sm.get('stops')}, "
                     f"open {sm.get('open')}, unfilled/cancelled {sm.get('unfilled_or_cancelled')}, net {sm.get('net_r')}R")
        for i, c in enumerate(cands[-8:], 1):  # last up to 8
            lines.append(
                f"\n#{i} {c['side']} entry={c['entry']:.5f} "
                f"SL={c['stop']:.5f} TP={c['target']:.5f} RR=1:{c['rr']}"
            )
            lines.append(f"  Style: {c.get('style')} · Outcome after signal: {c['outcome']}")
            if c.get("invalidation"):
                lines.append(f"  Invalidation rule: {c['invalidation']}")
            for e in c.get("evidence") or []:
                lines.append(f"  • {e}")

    lines.append("")
    lines.append("Note: experimental rules; no costs/slippage. Not financial advice.")
    return "\n".join(lines)


RR_BUCKETS = [(0.0, 1.0, "<1"), (1.0, 1.5, "1-1.5"), (1.5, 2.0, "1.5-2"), (2.0, 3.0, "2-3"), (3.0, 1e9, "3+")]


def rr_study(candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Group simulated market-entry outcomes by planned R:R (run the replay with min_rr ~0 first).

    Win rate = targets / (targets + stops). Net R uses each trade's own planned R:R for wins and -1 for stops.
    """
    rows = []
    for lo, hi, label in RR_BUCKETS:
        group = [c for c in candidates if lo <= float(c["rr"]) < hi]
        wins = sum(1 for c in group if c["outcome"] == "target")
        losses = sum(1 for c in group if str(c["outcome"]).startswith("stop"))
        open_ = sum(1 for c in group if c["outcome"] == "open")
        resolved = wins + losses
        net = sum(c["r"] for c in group if c.get("r") is not None)
        rows.append({
            "bucket": label, "setups": len(group), "targets": wins, "stops": losses, "open": open_,
            "win_rate": round(wins / resolved, 2) if resolved else None,
            "net_r": round(net, 2),
            "expectancy_r": round(net / resolved, 2) if resolved else None,
        })
    return rows


def format_rr_study(symbol: str, rows: list[dict[str, Any]], bars: int) -> str:
    total = sum(r["setups"] for r in rows)
    lines = [f"R:R study - {symbol} ({bars} bars, {total} setups that passed every candle rule; outcomes at market entry)", ""]
    lines.append("R:R bucket | setups | win/loss | win% | net R | per trade")
    for r in rows:
        wr = f"{int(r['win_rate'] * 100)}%" if r["win_rate"] is not None else "-"
        ex = f"{r['expectancy_r']:+.2f}R" if r["expectancy_r"] is not None else "-"
        lines.append(f"  {r['bucket']:>6} | {r['setups']:>3} | {r['targets']}/{r['stops']} | {wr:>4} | {r['net_r']:+.1f} | {ex}")
    lines += ["", "Read: a bucket with positive 'per trade' and enough setups (30+) is worth allowing.",
              "Small samples lie: do not change the minimum R:R from fewer than ~30 setups per bucket.",
              "No costs/slippage. Experimental, not financial advice."]
    return "\n".join(lines)
