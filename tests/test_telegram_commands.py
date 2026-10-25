"""End-to-end style tests for the Telegram command bot using fake Telegram + fake Deriv."""
import asyncio
import unittest
from unittest import mock

from monitoring import telegram_commands as tc
from tests.test_engine_positive_path import build

STATUS = {
    "started_at": 1, "last_cycle_at": 2, "cycles": 5, "alerts_enabled": False, "telegram_enabled": True,
    "stage_tally": {}, "candidates": [{"symbol": "cryBTCUSD", "side": "BUY", "entry": 1.0, "stop": 0.9,
                                       "target": 1.3, "rr": 3.0, "found_at": 1}],
    "symbols": {
        "frxXAUUSD": {"checked_at": 1, "data": "stale_or_market_closed"},
        "cryBTCUSD": {"checked_at": 1, "data": "ok", "status": "NO_TRADE", "side": None,
                      "stage": "target", "why_not": ["RR too low"], "evidence": ["x"]},
    },
}


class CommandTextTests(unittest.TestCase):
    def test_symbol_aliases(self):
        self.assertEqual(tc.resolve_symbol("gold"), "frxXAUUSD")
        self.assertEqual(tc.resolve_symbol("BTC"), "cryBTCUSD")
        self.assertEqual(tc.resolve_symbol("eur/usd"), "frxEURUSD")
        self.assertIsNone(tc.resolve_symbol("nonsense"))

    def test_all_text_commands_return_text(self):
        for cmd in ["/start", "/help", "/status", "/candidates", "/symbols", "/pair gold", "/pair",
                    "/pair zzz", "/gold", "/eur", "/gbp", "/btc", "/unknown"]:
            out = tc.handle_command(cmd, lambda: STATUS)
            self.assertIsInstance(out, str)
            self.assertTrue(out)
        self.assertIn("market", tc.handle_command("/gold", lambda: STATUS).lower())
        self.assertIn("RR too low", tc.handle_command("/btc", lambda: STATUS))
        self.assertEqual(tc.handle_command("/replay btc", lambda: STATUS), "__REPLAY__")


class CommandLoopTests(unittest.IsolatedAsyncioTestCase):
    async def test_loop_answers_authorized_chat_only_and_runs_replay(self):
        sent = []
        updates = [[
            {"update_id": 1, "message": {"chat": {"id": 999}, "text": "/status"}},       # stranger
            {"update_id": 2, "message": {"chat": {"id": 111}, "text": "hello"}},         # not a command
            {"update_id": 3, "message": {"chat": {"id": 111}, "text": "/status"}},
            {"update_id": 4, "message": {"chat": {"id": 111}, "text": "/gold"}},
            {"update_id": 5, "message": {"chat": {"id": 111}, "text": "/replay btc 200"}},
        ]]

        async def fake_updates(token, offset):
            if updates:
                return updates.pop(0)
            raise asyncio.CancelledError()

        async def fake_send(token, chat_id, text):
            sent.append((chat_id, text))

        m15, m5 = build()

        async def fake_candles(self, symbol, timeframe, count=120):
            return m15 if timeframe == "15m" else m5

        with mock.patch.object(tc, "get_updates", fake_updates), \
             mock.patch.object(tc, "send_message", fake_send), \
             mock.patch("monitoring.market_data.DerivMarketData.candles", fake_candles):
            with self.assertRaises(asyncio.CancelledError):
                await tc.command_loop("TOKEN", "111", lambda: STATUS)

        chats = {c for c, _ in sent}
        self.assertEqual(chats, {"111"})               # nothing was sent to the stranger
        texts = [t for _, t in sent]
        self.assertTrue(any("Monitor status" in t for t in texts))
        self.assertTrue(any("XAUUSD" in t for t in texts))
        self.assertTrue(any("Running replay" in t for t in texts))
        self.assertTrue(any("Replay" in t and "gate tally" in t for t in texts))


if __name__ == "__main__":
    unittest.main()
