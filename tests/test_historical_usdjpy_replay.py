import json
import unittest
from pathlib import Path


FIXTURE = Path(__file__).parent / "fixtures" / "usdjpy_5m_replay.json"


class HistoricalUsdJpyReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = json.loads(FIXTURE.read_text(encoding="utf-8"))
        cls.candles = cls.data["candles"]

    def test_fixture_has_ordered_real_ohlc_candles(self):
        self.assertEqual(self.data["symbol"], "frxUSDJPY")
        self.assertEqual(self.data["granularity"], 300)
        self.assertGreaterEqual(len(self.candles), 20)
        epochs = [c["epoch"] for c in self.candles]
        self.assertEqual(epochs, sorted(set(epochs)))
        for c in self.candles:
            self.assertLessEqual(c["low"], min(c["open"], c["close"]))
            self.assertGreaterEqual(c["high"], max(c["open"], c["close"]))

    def test_historical_rejection_confirmation_and_target(self):
        # User-annotated references: rejection ~156.960, confirmation band
        # 156.900-156.870, entry 156.874, stop 156.975, target 156.571.
        rejection = next(
            c for c in self.candles
            if c["high"] >= 156.960 and c["close"] < 156.960
        )
        self.assertEqual(rejection["epoch"], 1792754700)
        self.assertEqual(rejection["high"], 156.962)
        self.assertEqual(rejection["close"], 156.946)

        confirmation = next(
            c for c in self.candles
            if c["epoch"] > rejection["epoch"] and c["close"] < 156.870
        )
        self.assertEqual(confirmation["epoch"], 1792756800)
        self.assertEqual(confirmation["close"], 156.853)

        target_hit = next(
            c for c in self.candles
            if c["epoch"] > confirmation["epoch"] and c["low"] <= 156.571
        )
        self.assertEqual(target_hit["epoch"], 1792758900)
        self.assertEqual(target_hit["low"], 156.566)

        # If entry waits for the first close below 156.870, it no longer meets
        # the strategy's minimum 3R using the original stop and target.
        entry = confirmation["close"]
        risk = 156.975 - entry
        reward = entry - 156.571
        rr = reward / risk
        self.assertAlmostEqual(rr, 2.3114754098, places=6)
        self.assertLess(rr, 3.0)


if __name__ == "__main__":
    unittest.main()
