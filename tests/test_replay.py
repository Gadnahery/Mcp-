import unittest

from monitoring.replay_engine import run_replay
from tests.test_engine_positive_path import build


class ReplayTests(unittest.TestCase):
    def test_replay_finds_the_textbook_setup_once_and_tallies_gates(self):
        m15, m5 = build()
        # replay needs warmup candles before the setup; use a small warmup for synthetic data
        result = run_replay("TEST", m15, m5, warmup=20)
        self.assertEqual(len(result["candidates"]), 1)
        self.assertEqual(result["candidates"][0]["side"], "BUY")
        self.assertIn("CANDIDATE", result["tally"])
        self.assertGreater(sum(result["tally"].values()), 1)


if __name__ == "__main__":
    unittest.main()


class StatusTests(unittest.TestCase):
    def test_record_analysis_tracks_candidates_and_stage_tally(self):
        import monitor_worker
        from monitoring.strategy import analyze_setup
        monitor_worker.STATUS.update(stage_tally={}, symbols={}, candidates=[])
        m15, m5 = build()
        monitor_worker.record_analysis("TEST", analyze_setup("TEST", m15, m5), now=1)
        self.assertEqual(monitor_worker.STATUS["stage_tally"].get("CANDIDATE"), 1)
        self.assertEqual(monitor_worker.STATUS["candidates"][0]["side"], "BUY")
        self.assertEqual(monitor_worker.STATUS["symbols"]["TEST"]["status"], "CANDIDATE")
