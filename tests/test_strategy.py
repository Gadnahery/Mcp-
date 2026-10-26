import unittest

from monitoring.strategy import _directional_confirmation, _dominance, analyze_setup, detect_candidate


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

    def test_two_bearish_body_closes_confirm_sell_control(self):
        candles = [
            {"open": 1.3376, "close": 1.3375, "high": 1.3377, "low": 1.3374, "epoch": 1},
            {"open": 1.3375, "close": 1.3373, "high": 1.3376, "low": 1.3372, "epoch": 2},
        ]
        self.assertEqual(_directional_confirmation(candles, "SELL"), (1, 2))

    def test_three_bullish_body_closes_strengthen_buy_control(self):
        candles = [
            {"open": 1.1200, "close": 1.1201, "high": 1.1202, "low": 1.1199, "epoch": 1},
            {"open": 1.1201, "close": 1.1203, "high": 1.1204, "low": 1.1200, "epoch": 2},
            {"open": 1.1203, "close": 1.1205, "high": 1.1206, "low": 1.1202, "epoch": 3},
        ]
        self.assertEqual(_directional_confirmation(candles, "BUY"), (2, 3))

    def test_same_colour_without_progress_does_not_confirm(self):
        candles = [
            {"open": 1.10, "close": 1.09, "high": 1.11, "low": 1.08, "epoch": 1},
            {"open": 1.09, "close": 1.095, "high": 1.10, "low": 1.08, "epoch": 2},
        ]
        self.assertIsNone(_directional_confirmation(candles, "SELL"))

    def test_no_signal_when_timeframe_data_is_missing(self):
        self.assertIsNone(detect_candidate("TEST", [], []))

    def test_no_signal_when_higher_timeframe_dominance_disagrees(self):
        m15 = candles_from_closes([20, 19, 18, 17, 16, 15, 14, 13, 12, 11, 10], step=900)
        m5 = candles_from_closes([10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20], step=300)
        self.assertIsNone(detect_candidate("TEST", m15, m5))

    def test_no_trade_on_flat_ambiguous_market(self):
        flat = candles_from_closes([10] * 30, spread=0.2)
        result = analyze_setup("TEST", flat, flat)
        self.assertEqual(result.status, "NO_TRADE")
        self.assertIsNone(result.candidate)

    def test_two_timeframe_mode_runs_without_hourly_data(self):
        flat = candles_from_closes([10] * 30, spread=0.2)
        result = analyze_setup("TEST", flat, flat)
        self.assertEqual(result.status, "NO_TRADE")
        self.assertIsNone(result.candidate)

    def test_unclear_15m_does_not_reject_clear_5m_as_opposed(self):
        m15 = candles_from_closes([10, 11, 10, 11, 10, 11, 10, 11, 10, 11,
                                   10, 11, 10, 11, 10, 11, 10, 11, 10, 11,
                                   10, 11, 10, 11], spread=0.2, step=900)
        m5 = candles_from_closes(list(range(10, 40)), spread=0.2, step=300)
        result = analyze_setup("TEST", m15, m5)
        self.assertNotEqual(result.stage, "approach")

    def test_sweep_alone_never_returns_candidate(self):
        # Data without clear higher-timeframe close-to-close dominance cannot pass context.
        closes = [10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11, 10, 11]
        data = candles_from_closes(closes)
        self.assertIsNone(detect_candidate("TEST", data, data))


if __name__ == "__main__":
    unittest.main()
