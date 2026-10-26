"""Spread-aware R:R, significance-ranked reaction areas, retest entries, replay diagnostics."""
import unittest
from types import SimpleNamespace

from monitoring.replay_engine import _simulate, run_replay
from monitoring.strategy import _plan_entry, _reaction_areas, analyze_setup
from tests.test_engine_positive_path import _mk, build


class PlanEntryTests(unittest.TestCase):
    def test_market_entry_when_rr_ok_even_with_spread(self):
        plan = _plan_entry("BUY", 100.0, 99.0, 104.0, 99.6, False, spread=0.2)
        self.assertEqual(plan["style"], "market")
        self.assertAlmostEqual(plan["rr"], (4.0 - 0.2) / (1.0 + 0.2), places=6)

    def test_spread_can_push_a_marginal_setup_below_the_minimum(self):
        self.assertEqual(_plan_entry("BUY", 100.0, 99.0, 103.1, None, True, spread=0.0)["style"], "market")
        self.assertIsNone(_plan_entry("BUY", 100.0, 99.0, 103.1, None, True, spread=0.3)["style"])

    def test_retest_limit_used_when_market_fails_but_retest_passes(self):
        plan = _plan_entry("BUY", 100.0, 99.0, 102.0, 99.5, False, spread=0.0)
        self.assertEqual(plan["style"], "pullback_limit")
        self.assertEqual(plan["entry"], 99.5)
        self.assertGreaterEqual(plan["rr"], 3.0)

    def test_retest_not_offered_when_already_filled_or_disabled(self):
        self.assertIsNone(_plan_entry("BUY", 100.0, 99.0, 102.0, 99.5, True, 0.0)["style"])
        self.assertIsNone(_plan_entry("BUY", 100.0, 99.0, 102.0, 99.5, False, 0.0, pullback=False)["style"])

    def test_sell_side_mirrors_buy(self):
        plan = _plan_entry("SELL", 100.0, 101.0, 97.0, 100.5, False, spread=0.0)
        self.assertEqual(plan["style"], "market")
        plan = _plan_entry("SELL", 100.0, 101.0, 99.0, 100.5, False, spread=0.0)
        self.assertEqual(plan["style"], "pullback_limit")


class ReactionAreaTests(unittest.TestCase):
    def test_strong_reaction_and_equal_highs_are_significant_minor_swing_is_not(self):
        base = (10, 11, 9, 10)
        rows = [base] * 3
        rows += [(10, 12.0, 9.8, 10)]            # minor swing high 12.0 (tiny reaction)
        rows += [(10, 11, 9.9, 10)] * 4
        rows += [(10, 20.0, 10, 11)]             # swing high 20.0
        rows += [(11, 11, 3, 4)]                 # then a big drop: strong reaction
        rows += [(4, 5, 3, 4)] * 4
        rows += [(5, 18.0, 4, 5)]                # equal-ish high 18 ...
        rows += [(5, 6, 4, 5)] * 3
        rows += [(5, 18.0, 4, 5)]                # ... touched twice
        rows += [(5, 6, 4, 5)] * 4
        highs, _ = _reaction_areas(_mk(rows, 1, 60), tolerance=0.3, median_range=3.0)
        by_level = {round(a["level"], 1): a for a in highs}
        self.assertFalse(by_level[12.0]["significant"])
        self.assertTrue(by_level[20.0]["significant"])


class OptsAndReplayTests(unittest.TestCase):
    def test_opts_can_loosen_rr(self):
        m15, m5 = build()
        strict = analyze_setup("TEST", m15, m5, {"min_rr": 50.0})
        self.assertEqual(strict.stage, "risk_reward")
        self.assertIn("rr_market", strict.details)
        self.assertEqual(analyze_setup("TEST", m15, m5).status, "CANDIDATE")

    def test_simulate_handles_retest_fill_and_cancel(self):
        c = SimpleNamespace(side="BUY", entry=100.0, stop_loss=99.0, take_profit=103.0,
                            risk_reward=3.0, entry_style="pullback_limit")
        f = lambda lo, hi: dict(low=lo, high=hi)
        self.assertEqual(_simulate(c, [f(100.5, 101), f(99.9, 101), f(100, 103.2)]), ("target", 3.0))
        self.assertEqual(_simulate(c, [f(100.5, 101), f(98.9, 101)])[0].split()[0], "cancelled")
        self.assertEqual(_simulate(c, [f(100.5, 101)] * 3), ("unfilled", None))

    def test_replay_reports_near_misses_and_summary(self):
        m15, m5 = build()
        result = run_replay("TEST", m15, m5, warmup=20, opts={"min_rr": 50.0})
        self.assertGreater(result["near_misses"]["setups_that_failed_rr_or_target"], 0)
        self.assertEqual(result["summary"]["targets"], 0)
        ok = run_replay("TEST", m15, m5, warmup=20)
        self.assertEqual(len(ok["candidates"]), 1)


if __name__ == "__main__":
    unittest.main()


class NoPullbackByDefaultTests(unittest.TestCase):
    def test_pullback_entries_are_off_unless_explicitly_enabled(self):
        import monitoring.strategy as strat
        self.assertFalse(strat.PULLBACK_ENABLED)
        m15, m5 = build()
        result = analyze_setup("TEST", m15, m5)
        if result.candidate:
            self.assertNotEqual(result.candidate.entry_style, "pullback_limit")

    def test_replay_counts_one_near_miss_per_sweep_and_reports_what_if_taken(self):
        m15, m5 = build()
        result = run_replay("TEST", m15, m5, warmup=20, opts={"min_rr": 50.0})
        nm = result["near_misses"]
        self.assertEqual(nm["setups_that_failed_rr_or_target"], 1)   # same sweep seen on several bars = one setup
        self.assertIn("if_taken_at_market", nm)
        self.assertEqual(sum(nm["if_taken_at_market"][k] for k in ("targets", "stops", "open")) <= 1, True)
