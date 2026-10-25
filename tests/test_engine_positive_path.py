"""The engine must be able to produce a candidate for a textbook setup.

Synthetic data: 15M has a clear swing low (100.0) and a far swing high (160.0); 5M
approaches the low, sweeps it slightly, reclaims, forms a compact base, then closes
decisively above the base. This guards against gates that silently reject everything.
"""
import unittest

from monitoring.strategy import analyze_setup


def _mk(rows, start, step):
    return [dict(epoch=start + i * step, open=o, high=h, low=l, close=c) for i, (o, h, l, c) in enumerate(rows)]


def build(depth=0.3):
    pattern = [0, 3, -2, 4, -3, 2, -4, 3, -2, 5, -3, 2]
    rows, px = [], 110.0
    for k in range(60):
        o, c = px, px + pattern[k % len(pattern)] * 0.8
        rows.append((o, max(o, c) + 2, min(o, c) - 2, c))
        px = c

    def force(i, low=None, high=None):
        o, h, l, c = rows[i]
        if low is not None:
            l, o, c = low, max(o, low + 1), max(c, low + 1)
        if high is not None:
            h = high
        rows[i] = (o, max(h, o, c), min(l, o, c), c)

    force(40, low=100.0)
    force(50, high=160.0)
    m15 = _mk(rows, 1_700_000_000, 900)

    closes = [109, 108.6, 109.2, 108.8, 109.1, 108.7, 109.0, 108.5] + \
             [108, 107.5, 107, 106.2, 105.5, 104.8, 104, 103.2, 102.5, 101.8, 101.2, 100.8]
    r5, prev = [], closes[0]
    for c in closes:
        r5.append((prev, max(prev, c) + 0.3, min(prev, c) - 0.3, c))
        prev = c
    r5.append((prev, prev + 0.2, 100.0 - depth, 100.4))           # sweep + reclaim
    prev = 100.4
    for o, c in [(100.4, 100.6), (100.6, 100.5), (100.5, 100.7)]:  # compact base
        r5.append((o, max(o, c) + 0.2, min(o, c) - 0.2, c))
        prev = c
    r5.append((prev, 102.2, prev - 0.1, 102.0))                    # decisive close
    r5.append((102.0, 102.4, 101.9, 102.3))                        # forming candle (ignored)
    return m15, _mk(r5, 1_700_000_000 + 60 * 900, 300)


class PositivePathTests(unittest.TestCase):
    def test_textbook_buy_produces_candidate_with_structural_stop_and_3r(self):
        m15, m5 = build()
        result = analyze_setup("TEST", m15, m5)
        self.assertEqual(result.status, "CANDIDATE", result.missing)
        c = result.candidate
        self.assertEqual(c.side, "BUY")
        self.assertAlmostEqual(c.stop_loss, 99.7, places=6)   # beyond the swept low
        self.assertGreaterEqual(c.risk_reward, 3.0)

    def test_no_candidate_without_the_confirming_close(self):
        m15, m5 = build()
        m5[-2] = dict(m5[-2], close=100.9, high=101.0)         # no close beyond base
        self.assertNotEqual(analyze_setup("TEST", m15, m5).status, "CANDIDATE")


if __name__ == "__main__":
    unittest.main()


class SweepAndFreshnessTests(unittest.TestCase):
    def test_deeper_sweep_within_range_multiple_is_detected(self):
        m15, m5 = build(depth=2.0)
        self.assertEqual(analyze_setup("TEST", m15, m5).status, "CANDIDATE")

    def test_sweep_far_beyond_the_level_is_not_a_sweep(self):
        m15, m5 = build(depth=9.0)  # more than 0.75x the median 15M range
        result = analyze_setup("TEST", m15, m5)
        self.assertNotEqual(result.status, "CANDIDATE")
        self.assertEqual(result.stage, "location_or_sweep")

    def test_old_confirmation_is_stale_and_rejected(self):
        m15, m5 = build()
        last = m5[-2]["close"]
        extra = []
        for k in range(1, 4):  # three more completed candles after the confirming close
            o = last + (k - 1) * 0.2
            extra.append(dict(epoch=m5[-1]["epoch"] + 300 * k, open=o, high=o + 0.4, low=o - 0.1, close=o + 0.2))
        # drop the old forming candle, append completed extras plus a new forming candle
        m5b = m5[:-1] + extra + [dict(extra[-1], epoch=extra[-1]["epoch"] + 300)]
        result = analyze_setup("TEST", m15, m5b)
        self.assertNotEqual(result.status, "CANDIDATE")

    def test_equal_highs_count_as_one_swing_level(self):
        from monitoring.strategy import _swing_levels
        rows = [(10, 11, 9, 10)] * 3 + [(10, 15, 9, 10), (10, 15, 9, 10)] + [(10, 11, 9, 10)] * 3
        candles = _mk(rows, 1, 60)
        highs, _ = _swing_levels(candles)
        self.assertEqual(highs.count(15), 1)


def _impulse(post):
    """Approach + sweep from build(), then custom post-sweep candles (o, c), then a forming candle."""
    m15, m5 = build()
    head = m5[:21]  # 20 approach candles + the sweep candle
    out, t = list(head), head[-1]["epoch"]
    for k, (o, c) in enumerate(post, 1):
        out.append(dict(epoch=t + 300 * k, open=o, high=max(o, c) + 0.1, low=min(o, c) - 0.1, close=c))
    last = out[-1]["close"]
    out.append(dict(epoch=out[-1]["epoch"] + 300, open=last, high=last + 0.2, low=last - 0.1, close=last + 0.1))
    return m15, out


class DominancePathTests(unittest.TestCase):
    def test_impulsive_reversal_with_three_strong_closes_is_a_candidate(self):
        m15, m5 = _impulse([(100.4, 101.3), (101.3, 102.2), (102.2, 103.1)])
        result = analyze_setup("TEST", m15, m5)
        self.assertEqual(result.status, "CANDIDATE", (result.stage, result.missing))
        self.assertEqual(result.candidate.entry_style, "dominance_closes")
        self.assertEqual(result.candidate.side, "BUY")

    def test_two_strong_closes_are_not_enough(self):
        m15, m5 = _impulse([(100.4, 101.3), (101.3, 102.2), (102.2, 102.0)])
        self.assertNotEqual(analyze_setup("TEST", m15, m5).status, "CANDIDATE")

    def test_three_tiny_bodied_closes_do_not_count_as_control(self):
        # closes rise but bodies are slivers inside long wicks: not strong control
        post = [(100.40, 100.43), (100.43, 100.46), (100.46, 100.49)]
        m15, m5 = _impulse(post)
        for c in m5[21:24]:
            c["high"] += 1.0
            c["low"] -= 1.0
        self.assertNotEqual(analyze_setup("TEST", m15, m5).status, "CANDIDATE")

    def test_streak_must_finish_beyond_the_sweep_candle(self):
        # rising closes but never clearing the sweep candle's high (100.2): no control shown
        post = [(100.00, 100.05), (100.05, 100.10), (100.10, 100.15)]
        m15, m5 = _impulse(post)
        self.assertNotEqual(analyze_setup("TEST", m15, m5).status, "CANDIDATE")
