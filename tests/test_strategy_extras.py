"""Spread-aware R:R, significance-ranked reaction areas, retest entries, replay diagnostics."""
import unittest
from types import SimpleNamespace

from monitoring.replay_engine import _simulate, run_replay
from monitoring.strategy import _plan_entry, _reaction_areas, _select_target_area, _strong_counter_bias_confirmation, analyze_setup
from tests.synth import extend_5m, with_1m
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


class CounterBiasConfirmationTests(unittest.TestCase):
    def test_sell_counter_bias_needs_three_strong_closes_beyond_sweep_low(self):
        sweep = {"low": 100.0, "high": 104.0}
        strong = [
            {"open": 102.0, "high": 102.2, "low": 100.8, "close": 101.0},
            {"open": 101.0, "high": 101.2, "low": 99.8, "close": 100.0},
            {"open": 100.0, "high": 100.2, "low": 98.8, "close": 99.0},
        ]
        ok, reason = _strong_counter_bias_confirmation("SELL", sweep, strong)
        self.assertTrue(ok, reason)

    def test_counter_bias_rejected_if_final_close_does_not_break_sweep_boundary(self):
        sweep = {"low": 100.0, "high": 104.0}
        candles = [
            {"open": 103.0, "high": 103.2, "low": 102.0, "close": 102.2},
            {"open": 102.2, "high": 102.4, "low": 101.0, "close": 101.2},
            {"open": 101.2, "high": 101.4, "low": 100.2, "close": 100.4},
        ]
        ok, reason = _strong_counter_bias_confirmation("SELL", sweep, candles)
        self.assertFalse(ok)
        self.assertIn("sweep-candle low", reason)

    def test_counter_bias_rejected_for_weak_or_nonprogressing_candles(self):
        sweep = {"low": 100.0, "high": 104.0}
        weak = [
            {"open": 103.0, "high": 104.0, "low": 102.0, "close": 102.9},
            {"open": 102.9, "high": 103.0, "low": 101.0, "close": 101.1},
            {"open": 101.1, "high": 101.2, "low": 99.0, "close": 99.1},
        ]
        ok, _ = _strong_counter_bias_confirmation("SELL", sweep, weak)
        self.assertFalse(ok)


class TargetSelectionTests(unittest.TestCase):
    def test_nearest_significant_intraday_target_beats_distant_15m_target(self):
        areas_5m = [
            {"level": 4042.0, "significant": True, "touches": 2, "reaction": 1.5},
        ]
        areas_15m = [
            {"level": 4000.0, "significant": True, "touches": 1, "reaction": 12.0},
        ]
        target = _select_target_area("SELL", 4050.0, areas_5m, areas_15m)
        self.assertIsNotNone(target)
        self.assertEqual(target["level"], 4042.0)
        self.assertEqual(target["timeframe"], "5M")

    def test_target_must_be_beyond_entry_and_significant_by_default(self):
        areas_5m = [
            {"level": 4052.0, "significant": True, "touches": 2, "reaction": 1.5},
            {"level": 4048.0, "significant": False, "touches": 1, "reaction": 0.1},
        ]
        areas_15m = []
        self.assertIsNone(_select_target_area("SELL", 4050.0, areas_5m, areas_15m))
        target = _select_target_area("SELL", 4050.0, areas_5m, areas_15m, "nearest")
        self.assertEqual(target["level"], 4048.0)

    def test_buy_target_is_nearest_valid_area_above_entry(self):
        areas_5m = [{"level": 101.5, "significant": True, "touches": 2, "reaction": 1.0}]
        areas_15m = [{"level": 105.0, "significant": True, "touches": 1, "reaction": 4.0}]
        target = _select_target_area("BUY", 100.0, areas_5m, areas_15m)
        self.assertEqual(target["level"], 101.5)


class OptsAndReplayTests(unittest.TestCase):
    def test_opts_can_loosen_rr(self):
        m15, m5 = build()
        strict = analyze_setup("TEST", m15, m5, with_1m(m5), {"min_rr": 50.0, "spread": 0.0})
        self.assertEqual(strict.stage, "risk_reward")
        self.assertIn("rr_market", strict.details)
        self.assertEqual(analyze_setup("TEST", m15, m5, with_1m(m5), {"spread": 0.0}).status, "CANDIDATE")

    def test_simulate_handles_retest_fill_and_cancel(self):
        c = SimpleNamespace(side="BUY", entry=100.0, stop_loss=99.0, take_profit=103.0,
                            risk_reward=3.0, entry_style="pullback_limit")
        f = lambda lo, hi: dict(low=lo, high=hi)
        self.assertEqual(_simulate(c, [f(100.5, 101), f(99.9, 101), f(100, 103.2)]), ("target", 3.0))
        self.assertEqual(_simulate(c, [f(100.5, 101), f(98.9, 101)])[0].split()[0], "cancelled")
        self.assertEqual(_simulate(c, [f(100.5, 101)] * 3), ("unfilled", None))

    def test_replay_reports_near_misses_and_summary(self):
        m15, m5 = build()
        m5x = extend_5m(m5)
        result = run_replay("TEST", m15, m5x, m1=with_1m(m5x), warmup=20, opts={"min_rr": 50.0, "spread": 0.0})
        self.assertGreater(result["near_misses"]["setups_that_failed_rr_or_target"], 0)
        self.assertEqual(result["summary"]["targets"], 0)
        ok = run_replay("TEST", m15, m5x, m1=with_1m(m5x), warmup=20, opts={"spread": 0.0})
        self.assertEqual(len(ok["candidates"]), 1)


if __name__ == "__main__":
    unittest.main()


class NoPullbackByDefaultTests(unittest.TestCase):
    def test_pullback_entries_are_off_unless_explicitly_enabled(self):
        import monitoring.strategy as strat
        self.assertFalse(strat.PULLBACK_ENABLED)
        m15, m5 = build()
        result = analyze_setup("TEST", m15, m5, with_1m(m5), {"spread": 0.0})
        if result.candidate:
            self.assertNotEqual(result.candidate.entry_style, "pullback_limit")

    def test_replay_counts_one_near_miss_per_sweep_and_reports_what_if_taken(self):
        m15, m5 = build()
        m5x = extend_5m(m5)
        result = run_replay("TEST", m15, m5x, m1=with_1m(m5x), warmup=20, opts={"min_rr": 50.0, "spread": 0.0})
        nm = result["near_misses"]
        self.assertEqual(nm["setups_that_failed_rr_or_target"], 1)   # same sweep seen on several bars = one setup
        self.assertIn("if_taken_at_market", nm)
        self.assertEqual(sum(nm["if_taken_at_market"][k] for k in ("targets", "stops", "open")) <= 1, True)


class StudyAndCoverageTests(unittest.TestCase):
    def test_rr_study_buckets_wins_losses_and_expectancy(self):
        from monitoring.replay_engine import format_rr_study, rr_study
        cands = [
            {"rr": 0.5, "outcome": "target", "r": 0.5}, {"rr": 0.6, "outcome": "stop", "r": -1.0},
            {"rr": 1.2, "outcome": "target", "r": 1.2}, {"rr": 1.3, "outcome": "target", "r": 1.3},
            {"rr": 3.4, "outcome": "stop", "r": -1.0}, {"rr": 3.5, "outcome": "open", "r": None},
        ]
        rows = {r["bucket"]: r for r in rr_study(cands)}
        self.assertEqual(rows["<1"]["setups"], 2)
        self.assertEqual((rows["1-1.5"]["targets"], rows["1-1.5"]["stops"]), (2, 0))
        self.assertAlmostEqual(rows["1-1.5"]["expectancy_r"], 1.25)
        self.assertEqual(rows["3+"]["open"], 1)
        self.assertIn("per trade", format_rr_study("TEST", rr_study(cands), 100))

    def test_replay_skips_bars_without_1m_history_instead_of_calling_them_no_trade(self):
        m15, m5 = build()
        m5x = extend_5m(m5)
        m1 = with_1m(m5x)
        short_m1 = [c for c in m1 if c["epoch"] >= m5x[10]["epoch"]]   # 1M only covers the later part
        result = run_replay("TEST", m15, m5x, m1=short_m1, warmup=5)
        self.assertGreater(result["bars_skipped_no_1m"], 0)
        self.assertEqual(result["bars_evaluated"] + result["bars_skipped_no_1m"], len(m5x) - 5 - 1)
