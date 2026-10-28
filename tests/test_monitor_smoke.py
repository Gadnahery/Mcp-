"""Smoke test: run the real monitor loop on fake (fresh) candles with fake Telegram."""
import asyncio
import os
import tempfile
import time
import unittest
from unittest import mock

import monitor_worker
from monitoring.config import Settings
from tests.synth import with_1m
from tests.test_engine_positive_path import build


def _fresh(candles, gran, lag=20):
    """Shift candle times so the last *completed* candle just closed."""
    now = int(time.time())
    shift = (now - lag) - (int(candles[-2]["epoch"]) + gran)
    return [dict(c, epoch=int(c["epoch"]) + shift) for c in candles]


class MonitorSmokeTests(unittest.IsolatedAsyncioTestCase):
    async def _run(self, m15, m5, symbols=("frxGBPUSD",), cycles=3):
        sent = []
        sleeps = {"n": 0}

        async def fake_sleep(_):
            sleeps["n"] += 1
            if sleeps["n"] >= cycles:
                raise asyncio.CancelledError()

        async def fake_send(token, chat, text):
            sent.append(text)

        m1 = with_1m(m5)

        async def fake_candles(self, symbol, timeframe, count=120):
            return m15 if timeframe == "15m" else (m1 if timeframe == "1m" else m5)

        tmp = tempfile.mkdtemp()
        from monitoring.ledger import FileStore
        self.store = FileStore(os.path.join(tmp, "ledger.jsonl"))
        settings = Settings(symbols=symbols, telegram_bot_token="T", telegram_chat_id="1",
                            telegram_enabled=True, alerts_enabled=True,
                            state_path=os.path.join(tmp, "state.json"))
        monitor_worker.STATUS.update(stage_tally={}, symbols={}, candidates=[], cycles=0)
        with mock.patch.object(monitor_worker, "Settings", lambda: settings), \
             mock.patch.object(monitor_worker, "make_store", lambda: self.store), \
             mock.patch.object(monitor_worker, "send_telegram", fake_send), \
             mock.patch.object(monitor_worker, "command_loop", lambda *a, **k: asyncio.sleep(0)), \
             mock.patch("monitoring.market_data.DerivMarketData.candles", fake_candles), \
             mock.patch.object(monitor_worker.asyncio, "sleep", fake_sleep):
            with self.assertRaises(asyncio.CancelledError):
                await monitor_worker.run()
        return sent

    async def test_one_setup_sends_exactly_one_alert_across_cycles(self):
        m15, m5 = build()
        sent = await self._run(_fresh(m15, 900), _fresh(m5, 300, lag=250))  # 1M confirmation needs ~4 min after the 5M close
        alerts = [t for t in sent if "online" not in t and "alive" not in t]
        self.assertEqual(len(alerts), 1, sent)               # deduplicated over 3 cycles
        self.assertIn("frxGBPUSD", monitor_worker.STATUS["symbols"])
        self.assertEqual(len(monitor_worker.STATUS["candidates"]), 1)
        self.assertEqual(monitor_worker.STATUS["ledger"]["alerts"], 1)      # tracked automatically
        self.assertEqual(len(self.store.load()), 1)
        self.assertTrue(any("online" in t for t in sent))    # startup message

    async def test_stale_data_never_alerts(self):
        m15, m5 = build()                                     # 2023 timestamps = stale/closed market
        sent = await self._run(m15, m5)
        self.assertEqual([t for t in sent if "online" not in t], [])
        self.assertEqual(monitor_worker.STATUS["symbols"]["frxGBPUSD"]["data"], "stale_or_market_closed")


if __name__ == "__main__":
    unittest.main()
