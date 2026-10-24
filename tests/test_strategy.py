import unittest

from monitoring.strategy import detect_candidate


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
    def test_no_signal_when_timeframe_data_is_missing(self):
        self.assertIsNone(detect_candidate("TEST", [], [], [], []))

    def test_no_signal_when_higher_timeframe_dominance_disagrees(self):
        h1 = candles_from_closes([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20])
        m15 = candles_from_closes([20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10], step=900)
        m5 = candles_from_closes([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20], step=300)
        m1 = candles_from_closes([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20])
        self.assertIsNone(detect_candidate("TEST", h1, m15, m5, m1))


if __name__ == "__main__":
    unittest.main()
