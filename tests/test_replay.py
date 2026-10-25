import unittest

from replay import replay
from tests.test_engine_positive_path import build


class ReplayTests(unittest.TestCase):
    def test_replay_finds_the_textbook_setup_once_and_tallies_gates(self):
        m15, m5 = build()
        # replay needs warmup candles before the setup; use a small warmup for synthetic data
        tally, cands = replay("TEST", m15, m5, warmup=20)
        self.assertEqual(len(cands), 1)
        self.assertEqual(cands[0][0].side, "BUY")
        self.assertIn("CANDIDATE", tally)
        self.assertGreater(sum(tally.values()), 1)


if __name__ == "__main__":
    unittest.main()
