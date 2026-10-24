import unittest

from monitoring.strategy import _dominance, analyze_setup, detect_candidate


def candles_from_closes(closes, spread=0.5, start=1_700_000_000, step=60):
    result = []
    for i, close in enumerate(closes):
        prev = closes[i - 1] if i else close
        result.append({
            "epoch": start + i * step,
            "open": float(prev),
            "high": float(max(prev, close) + spread),
            "low": float(min(prev, close) - spread),
            "close": float(close),
        })
    return result


class StrategyTests(unittest.TestCase):
    def test_dominance_is_close_to_close_not_candle_colour(self):
        candles = [
            {"epoch": 1, "open": 10, "high": 12, "low": 9, "close": 11},
            {"epoch": 2, "open": 12, "high": 13, "low": 10, "close": 12},
            {"epoch": 3, "open": 13, "high": 14, "low": 11, "close": 13},
            {"epoch": 4, "open": 14, "high": 15, "low": 12, "close": 14},
        ]
        self.assertEqual(_dominance(candles, 3), "bullish")

    def test_no_signal_when_timeframe_data_is_missing(self):
        self.assertIsNone(detect_candidate("TEST", [], [], [], []))

    def test_no_signal_when_higher_timeframe_dominance_disagrees(self):
        h1 = candles_from_closes([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20], step=3600)
        m15 = candles_from_closes([20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10], step=900)
        m5 = candles_from_closes([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20], step=300)
        m1 = candles_from_closes([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20])
        self.assertIsNone(detect_candidate("TEST", h1, m15, m5, m1))

    def test_no_trade_on_flat_ambiguous_market(self):
        flat = candles_from_closes([10] * 30, spread=0.2)
        result = analyze_setup("TEST", flat, flat, flat, flat)
        self.assertEqual(result.status, "NO_TRADE")
        self.assertIsNone(result.candidate)

    def test_three_timeframe_mode_accepts_omitted_one_minute_data(self):
        flat = candles_from_closes([10] * 30, spread=0.2)
        result = analyze_setup("TEST", flat, flat, flat)
        self.assertEqual(result.status, "NO_TRADE")
        self.assertIsNone(result.candidate)

    def test_sweep_alone_never_returns_candidate(self):
        # Data without clear higher-timeframe close-to-close dominance cannot pass context.
        closes = [10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11]
        data = candles_from_closes(closes)
        self.assertIsNone(detect_candidate("TEST", data, data, data, data))


if __name__ == "__main__":
    unittest.main()
