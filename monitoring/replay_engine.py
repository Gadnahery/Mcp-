"""On-demand historical replay of the strategy engine using live Deriv candles."""
from __future__ import annotations

from collections import Counter
from typing import Any

from .strategy import analyze_setup


def run_replay(
    symbol: str,
    m15: list[dict[str, Any]],
    m5: list[dict[str, Any]],
    warmup: int = 60,
) -> dict[str, Any]:
    """Walk 5M candle-by-candle and collect gate tally + candidates with outcomes."""
    tally: Counter[str] = Counter()
    candidates: list[dict[str, Any]] = []
    seen: set[int] = set()
    last_analysis: dict[str, Any] | None = None

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
        view5 = [c for c in m5[: idx + 2] if int(c["epoch"]) <= now_epoch]
        view15 = [c for c in m15 if int(c["epoch"]) <= now_epoch]
        result = analyze_setup(symbol, view15, view5)
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
        if result.candidate and result.candidate.candle_epoch not in seen:
            seen.add(result.candidate.candle_epoch)
            c = result.candidate
            outcome = "open"
            for f in m5[idx + 1 :]:
                hit_stop = (
                    f["low"] <= c.stop_loss if c.side == "BUY" else f["high"] >= c.stop_loss
                )
                hit_tp = (
                    f["high"] >= c.take_profit if c.side == "BUY" else f["low"] <= c.take_profit
                )
                if hit_stop and hit_tp:
                    outcome = "stop (same candle; worst case)"
                    break
                if hit_stop:
                    outcome = "stop"
                    break
                if hit_tp:
                    outcome = "target"
                    break
            candidates.append({
                "side": c.side,
                "entry": c.entry,
                "stop": c.stop_loss,
                "target": c.take_profit,
                "rr": round(c.risk_reward, 2),
                "epoch": c.candle_epoch,
                "outcome": outcome,
                "invalidation": c.invalidation,
                "evidence": list(c.evidence)[-3:],
            })

    return {
        "symbol": symbol,
        "bars_evaluated": max(0, len(m5) - warmup - 1),
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
        lines.append(f"Setups found: {len(cands)}")
        for i, c in enumerate(cands[-8:], 1):  # last up to 8
            lines.append(
                f"\n#{i} {c['side']} entry={c['entry']:.5f} "
                f"SL={c['stop']:.5f} TP={c['target']:.5f} RR=1:{c['rr']}"
            )
            lines.append(f"  Outcome after signal: {c['outcome']}")
            if c.get("invalidation"):
                lines.append(f"  Invalidation rule: {c['invalidation']}")
            for e in c.get("evidence") or []:
                lines.append(f"  • {e}")

    lines.append("")
    lines.append("Note: experimental rules; no costs/slippage. Not financial advice.")
    return "\n".join(lines)
