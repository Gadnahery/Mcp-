"""Automatic alert tracking: every candidate is recorded, then scored later from real 1M candles.

This is the autonomous measurement loop: no human has to check charts to know whether alerts hit
their target or stop. Storage is pluggable: Supabase (survives restarts, recommended on Render free)
or a local JSONL file (lost when the free instance restarts).
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import urllib.parse
import urllib.request
from typing import Any

logger = logging.getLogger("ledger")
EXPIRE_SECONDS = 24 * 3600


class FileStore:
    def __init__(self, path: str) -> None:
        self.path = path

    def load(self) -> list[dict[str, Any]]:
        try:
            with open(self.path, encoding="utf-8") as fh:
                return [json.loads(line) for line in fh if line.strip()]
        except FileNotFoundError:
            return []

    def upsert(self, row: dict[str, Any]) -> None:
        rows = {r["id"]: r for r in self.load()}
        rows[row["id"]] = row
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        with open(self.path, "w", encoding="utf-8") as fh:
            for r in rows.values():
                fh.write(json.dumps(r) + "\n")


class SupabaseStore:
    """Supabase REST (PostgREST). Table SQL is in docs/DEPLOY_AND_TELEGRAM.md."""

    def __init__(self, url: str, key: str, table: str = "strategy_alerts") -> None:
        self.base = url.rstrip("/") + f"/rest/v1/{table}"
        self.headers = {"apikey": key, "Authorization": f"Bearer {key}", "Content-Type": "application/json"}

    def _call(self, req: urllib.request.Request) -> bytes:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.read()

    def load(self) -> list[dict[str, Any]]:
        q = urllib.parse.urlencode({"select": "*", "order": "alerted_at.desc", "limit": "2000"})
        return json.loads(self._call(urllib.request.Request(f"{self.base}?{q}", headers=self.headers)) or b"[]")

    def upsert(self, row: dict[str, Any]) -> None:
        headers = {**self.headers, "Prefer": "resolution=merge-duplicates,return=minimal"}
        req = urllib.request.Request(f"{self.base}?on_conflict=id", data=json.dumps(row).encode(), headers=headers, method="POST")
        self._call(req)


def make_store():
    url, key = os.getenv("SUPABASE_URL", ""), os.getenv("SUPABASE_SERVICE_KEY", "")
    if url and key:
        logger.info("Ledger storage: Supabase")
        return SupabaseStore(url, key)
    logger.warning("Ledger storage: local file (lost when the free Render instance restarts). Set SUPABASE_URL and SUPABASE_SERVICE_KEY for durable tracking.")
    return FileStore(os.getenv("LEDGER_PATH", "state/ledger.jsonl"))


def resolve(row: dict[str, Any], candles: list[dict[str, Any]], now: int) -> tuple[str, float | None, int | None] | None:
    """Return (status, r, closed_at) once the trade hit target/stop (or expired), else None.

    Same-candle stop+target is scored as a stop (worst case). The first eligible 1M
    candle open is used as the shadow entry fill, preventing a fill at a close already
    known only after confirmation."""
    buy = row["side"] == "BUY"
    fill_price: float | None = None
    signal_epoch = int(row.get("signal_epoch", row["entry_epoch"]))
    entry_epoch = int(row["entry_epoch"])
    for c in sorted(candles, key=lambda x: int(x["epoch"])):
        candle_epoch = int(c["epoch"])
        if candle_epoch < signal_epoch:
            continue
        if candle_epoch < entry_epoch:
            # The alert may arrive after the confirming candle's close. Do not score
            # movement before the next eligible minute as a filled trade.
            stop_before_fill = float(c["low"]) <= float(row["stop"]) if buy else float(c["high"]) >= float(row["stop"])
            target_before_fill = float(c["high"]) >= float(row["target"]) if buy else float(c["low"]) <= float(row["target"])
            if stop_before_fill:
                return "cancelled", None, candle_epoch + 60
            if target_before_fill:
                return "missed", None, candle_epoch + 60
            continue
        if fill_price is None:
            fill_price = float(c.get("open", row["entry"]))
            if (buy and fill_price >= float(row["target"])) or (not buy and fill_price <= float(row["target"])):
                return "missed", None, int(c["epoch"])
            if (buy and fill_price <= float(row["stop"])) or (not buy and fill_price >= float(row["stop"])):
                return "stop", -1.0, int(c["epoch"]) + 60
        hit_stop = float(c["low"]) <= float(row["stop"]) if buy else float(c["high"]) >= float(row["stop"])
        hit_tp = float(c["high"]) >= float(row["target"]) if buy else float(c["low"]) <= float(row["target"])
        if hit_stop and hit_tp:
            return "stop", -1.0, int(c["epoch"]) + 60
        if hit_stop:
            return "stop", -1.0, int(c["epoch"]) + 60
        if hit_tp:
            spread = max(0.0, float(row.get("assumed_spread", 0.0)))
            risk = abs(fill_price - float(row["stop"])) + spread
            reward = (float(row["target"]) - fill_price if buy else fill_price - float(row["target"])) - spread
            realized_r = round(reward / risk, 2) if risk > 0 and reward > 0 else 0.0
            return "target", realized_r, int(c["epoch"]) + 60
    if now - int(row["alerted_at"]) > EXPIRE_SECONDS:
        return "expired", None, now
    return None


class Ledger:
    def __init__(self, store) -> None:
        self.store = store
        self.rows: list[dict[str, Any]] = []

    async def load(self) -> None:
        try:
            self.rows = await asyncio.to_thread(self.store.load)
        except Exception:
            logger.exception("Ledger load failed; starting empty")
            self.rows = []

    async def _save(self, row: dict[str, Any]) -> None:
        try:
            await asyncio.to_thread(self.store.upsert, row)
        except Exception:
            logger.exception("Ledger save failed for %s", row.get("id"))

    async def record(self, c: Any, now: int | None = None) -> bool:
        now = now or int(time.time())
        rid = f"{c.symbol}:{c.side}:{c.candle_epoch}"
        if any(r["id"] == rid for r in self.rows):
            return False
        signal_epoch = int(c.candle_epoch) + 300
        next_full_minute = (now // 60 + 1) * 60
        row = {
            "id": rid, "symbol": c.symbol, "side": c.side, "entry": c.entry, "stop": c.stop_loss,
            "target": c.take_profit, "rr": round(float(c.risk_reward), 3), "style": c.entry_style,
            "alerted_at": now, "signal_epoch": signal_epoch,
            "entry_epoch": max(signal_epoch, next_full_minute), "status": "open",
            "assumed_spread": max(0.0, float(getattr(c, "assumed_spread", 0.0))),
            "closed_at": None, "r": None,
        }
        self.rows.append(row)
        await self._save(row)
        return True

    async def update(self, symbol: str, candles: list[dict[str, Any]], now: int | None = None) -> int:
        now = now or int(time.time())
        changed = 0
        for row in self.rows:
            if row["symbol"] != symbol or row.get("status") != "open":
                continue
            out = resolve(row, candles, now)
            if out:
                row["status"], row["r"], row["closed_at"] = out
                changed += 1
                await self._save(row)
        return changed

    def summary(self) -> dict[str, Any]:
        done = [r for r in self.rows if r["status"] in ("target", "stop")]
        ordered_done = sorted(done, key=lambda r: int(r.get("closed_at") or r["alerted_at"]))
        cumulative = peak = max_drawdown = 0.0
        consecutive_losses = current_losses = 0
        for row in ordered_done:
            value = float(row.get("r") or 0.0)
            cumulative += value
            peak = max(peak, cumulative)
            max_drawdown = max(max_drawdown, peak - cumulative)
            if value < 0:
                current_losses += 1
                consecutive_losses = max(consecutive_losses, current_losses)
            else:
                current_losses = 0
        wins = sum(1 for r in done if r["status"] == "target")
        by_symbol: dict[str, dict[str, Any]] = {}
        for r in self.rows:
            s = by_symbol.setdefault(r["symbol"], {"alerts": 0, "targets": 0, "stops": 0, "open": 0, "missed": 0, "net_r": 0.0, "closed": 0})
            s["alerts"] += 1
            s["targets"] += r["status"] == "target"
            s["stops"] += r["status"] == "stop"
            s["open"] += r["status"] == "open"
            s["missed"] += r["status"] == "missed"
            s["closed"] += r["status"] in ("target", "stop")
            s["net_r"] = round(s["net_r"] + (r["r"] or 0.0), 2)
        recent = sorted(self.rows, key=lambda r: r["alerted_at"], reverse=True)[:5]
        return {
            "alerts": len(self.rows), "open": sum(1 for r in self.rows if r["status"] == "open"),
            "targets": wins, "stops": sum(1 for r in self.rows if r["status"] == "stop"),
            "missed": sum(1 for r in self.rows if r["status"] == "missed"),
            "cancelled": sum(1 for r in self.rows if r["status"] == "cancelled"),
            "expired": sum(1 for r in self.rows if r["status"] == "expired"),
            "closed": len(done),
            "win_rate": round(wins / len(done), 2) if done else None,
            "net_r": round(sum(float(r["r"]) for r in done), 2),
            "expectancy_r": round(sum(float(r["r"]) for r in done) / len(done), 3) if done else None,
            "max_drawdown_r": round(max_drawdown, 2),
            "max_consecutive_losses": consecutive_losses,
            "by_symbol": by_symbol,
            "recent": [{k: r[k] for k in ("symbol", "side", "entry", "rr", "status", "r")} for r in recent],
        }


def format_stats(s: dict[str, Any] | None) -> str:
    if not s or not s.get("alerts"):
        return "No alerts recorded yet. Every candidate the monitor finds is tracked here automatically."
    wr = f"{int(s['win_rate'] * 100)}%" if s.get("win_rate") is not None else "-"
    lines = [
        "Alert scorecard (auto-scored from real candles)",
        f"Alerts {s['alerts']} · closed {s.get('closed', s['targets'] + s['stops'])} · targets {s['targets']} · stops {s['stops']} · missed {s.get('missed', 0)} · cancelled {s.get('cancelled', 0)} · open {s['open']} · expired {s['expired']}",
        f"Win rate {wr} · net {s['net_r']:+.2f}R · expectancy {s.get('expectancy_r', 0.0):+.2f}R/trade",
        f"Max drawdown {s.get('max_drawdown_r', 0.0):.2f}R · max losing streak {s.get('max_consecutive_losses', 0)}", "",
    ]
    for sym, v in s["by_symbol"].items():
        lines.append(f"• {sym}: {v['alerts']} alerts, {v['targets']}W/{v['stops']}L, open {v['open']}, {v['net_r']:+.2f}R")
    lines += ["", "Latest:"]
    for r in s["recent"]:
        lines.append(f"  {r['symbol']} {r['side']} @{r['entry']:g} 1:{r['rr']:.1f} -> {r['status']}" + (f" ({r['r']:+.2f}R)" if r["r"] is not None else ""))
    lines.append("\nSmall samples lie: judge after 30+ closed alerts.")
    return "\n".join(lines)
