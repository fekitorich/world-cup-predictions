"""Unit: the Elo second-opinion model's math — rating updates, the
margin multiplier, the goals regression and the lambda mapping."""
import math
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

import wc26_elo as E


def m(home, away, hg, ag, neutral=False, date="2024-01-01"):
    return {"date": date, "home": home, "away": away, "hg": hg, "ag": ag,
            "neutral": neutral}


class TestEloMechanics(unittest.TestCase):
    def test_expected_symmetric_on_neutral(self):
        self.assertAlmostEqual(E.expected(1500, 1500, neutral=True), 0.5)

    def test_home_advantage_tilts_expectation(self):
        self.assertGreater(E.expected(1500, 1500, neutral=False), 0.5)

    def test_update_zero_sum_and_direction(self):
        R, _ = E.replay([m("A", "B", 3, 0, neutral=True)])
        self.assertGreater(R["A"], E.START_RATING)
        self.assertLess(R["B"], E.START_RATING)
        self.assertAlmostEqual(R["A"] + R["B"], 2 * E.START_RATING, places=6)

    def test_upset_moves_more_than_expected_win(self):
        base = [m("A", "B", 2, 0, neutral=True)] * 6   # A established
        R1, _ = E.replay(base + [m("A", "B", 2, 0, neutral=True)])
        R2, _ = E.replay(base + [m("B", "A", 2, 0, neutral=True)])
        gain_expected = R1["A"]
        after_upset = R2["A"]
        self.assertLess(after_upset, gain_expected)

    def test_margin_multiplier_monotone(self):
        mm = [E.margin_mult(g, 0) for g in (1, 2, 4, 7)]
        self.assertEqual(mm, sorted(mm))

    def test_draw_still_updates_toward_expectation(self):
        base = [m("A", "B", 2, 0, neutral=True)] * 6
        R, _ = E.replay(base + [m("A", "B", 1, 1, neutral=True)])
        R0, _ = E.replay(base)
        self.assertLess(R["A"], R0["A"])   # favourite drawing loses points


class TestGoalsMap(unittest.TestCase):
    def test_regression_finds_rating_signal(self):
        samples = []
        for d, hg, ag in ((300, 3, 0), (300, 2, 1), (-300, 0, 2),
                          (-300, 1, 3), (0, 1, 1), (0, 2, 2)) * 30:
            samples.append({"diff": d, "neutral": True, "hg": hg, "ag": ag})
        g = E.fit_goals(samples)
        self.assertGreater(g["b"], 0)   # better rating -> more goals
        R = {"Strong": 1800, "Weak": 1500}
        l1, l2 = E.lambdas_elo(R, g, "Strong", "Weak", home_field=False)
        self.assertGreater(l1, l2)

    def test_home_field_adds_goals(self):
        g = {"a": math.log(1.3), "b": 0.8, "c": 0.25}
        R = {"A": 1500, "B": 1500}
        ln, _ = E.lambdas_elo(R, g, "A", "B", home_field=False)
        lh, _ = E.lambdas_elo(R, g, "A", "B", home_field=True)
        self.assertGreater(lh, ln)


if __name__ == "__main__":
    unittest.main()
