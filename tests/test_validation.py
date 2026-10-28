import unittest

from scripts.validate_strategy import metrics


class ValidationMetricTests(unittest.TestCase):
    def test_metrics_use_resolved_trades_and_report_drawdown(self):
        result = {
            "bars_evaluated": 100,
            "tally": {"CANDIDATE": 4},
            "candidates": [
                {"outcome": "target", "r": 3.0, "outcome_resolution": "1M"},
                {"outcome": "stop", "r": -1.0, "outcome_resolution": "1M"},
                {"outcome": "stop", "r": -1.0, "outcome_resolution": "5M fallback"},
                {"outcome": "open", "r": None, "outcome_resolution": "1M"},
            ],
        }
        m = metrics(result)
        self.assertEqual(m["resolved"], 3)
        self.assertAlmostEqual(m["win_rate"], 1 / 3, places=4)
        self.assertAlmostEqual(m["net_r"], 1.0)
        self.assertAlmostEqual(m["expectancy_r"], 1 / 3, places=3)
        self.assertEqual(m["max_drawdown_r"], 2.0)
        self.assertEqual(m["max_consecutive_losses"], 2)
        self.assertEqual(m["open_or_unresolved"], 1)


if __name__ == "__main__":
    unittest.main()
