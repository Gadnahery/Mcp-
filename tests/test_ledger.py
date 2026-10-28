import asyncio
import os
import tempfile
import unittest
from types import SimpleNamespace

from monitoring.ledger import FileStore, Ledger, format_stats, resolve


def cand(side="BUY", entry=100.0, stop=99.0, target=103.0, epoch=1000):
    return SimpleNamespace(symbol="TEST", side=side, entry=entry, stop_loss=stop, take_profit=target,
                           risk_reward=3.0, entry_style="decisive_close", candle_epoch=epoch, assumed_spread=0.0)


def candle(epoch, low, high, op=None):
    return dict(epoch=epoch, open=(low + high) / 2 if op is None else op,
                high=high, low=low, close=(low + high) / 2)


class LedgerTests(unittest.IsolatedAsyncioTestCase):
    async def test_records_once_and_scores_target_stop_and_worst_case(self):
        ledger = Ledger(FileStore(os.path.join(tempfile.mkdtemp(), "l.jsonl")))
        self.assertTrue(await ledger.record(cand(), now=1100))
        self.assertFalse(await ledger.record(cand(), now=1100))           # same alert is not double counted
        await ledger.record(cand(epoch=2000, stop=99.0, target=103.0), now=2100)
        await ledger.record(cand(side="SELL", entry=100, stop=101, target=97, epoch=3000), now=3100)
        candles = [candle(900, 90, 120),                                   # before entry: ignored
                   candle(1300, 99.5, 101, 100.0), candle(1360, 100, 103.2, 101.0),  # alert 1 -> target
                   candle(2300, 98.5, 100.5, 100.0),                        # alert 2 -> stop
                   candle(3300, 96.5, 101.5, 100.0)]                        # alert 3 -> stop AND target same candle: stop
        self.assertEqual(await ledger.update("TEST", candles, now=4000), 3)
        s = ledger.summary()
        self.assertEqual((s["targets"], s["stops"], s["open"]), (1, 2, 0))
        self.assertAlmostEqual(s["net_r"], 3.0 - 1.0 - 1.0)
        self.assertAlmostEqual(s["win_rate"], 0.33, places=2)
        self.assertIn("Win rate 33%", format_stats(s))

    async def test_persists_and_reloads_and_expires(self):
        path = os.path.join(tempfile.mkdtemp(), "l.jsonl")
        a = Ledger(FileStore(path))
        await a.record(cand(), now=1000)
        b = Ledger(FileStore(path))
        await b.load()
        self.assertEqual(len(b.rows), 1)
        await b.update("TEST", [candle(1300, 99.5, 100.5, 100.0)], now=1000 + 25 * 3600)
        self.assertEqual(b.rows[0]["status"], "expired")

    def test_resolve_ignores_candles_before_entry(self):
        row = dict(side="BUY", stop=99, target=103, rr=3.0, entry_epoch=1060, alerted_at=1000)
        self.assertIsNone(resolve(row, [candle(1000, 90, 120)], now=1100))

    def test_resolve_uses_next_one_minute_open_not_optimistic_signal_close(self):
        row = dict(side="BUY", entry=100, stop=99, target=103, rr=3.0,
                   assumed_spread=0.0, entry_epoch=1300, alerted_at=1000)
        candles = [
            candle(1300, 100.5, 101.5, 101.0),
            candle(1360, 100.5, 103.2, 101.5),
        ]
        result = resolve(row, candles, now=1400)
        self.assertEqual(result[0], "target")
        self.assertAlmostEqual(result[1], 1.0)  # actual fill at 101, not planned entry at 100

    def test_pre_alert_target_is_missed_and_pre_alert_stop_cancels_unfilled_candidate(self):
        base = dict(side="BUY", entry=100, stop=99, target=103, rr=3.0,
                    assumed_spread=0.0, signal_epoch=1300, entry_epoch=1380, alerted_at=1325)
        self.assertEqual(resolve(base, [candle(1300, 100.0, 103.2, 100.0)], now=1400)[0], "missed")
        self.assertEqual(resolve(base, [candle(1300, 98.5, 100.5, 100.0)], now=1400)[0], "cancelled")

    def test_empty_stats_message(self):
        self.assertIn("No alerts recorded", format_stats(None))


if __name__ == "__main__":
    unittest.main()
