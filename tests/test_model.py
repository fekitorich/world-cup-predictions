"""Unit tests for the statistical core (stdlib only, no network)."""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

from wc26_simulate import (params, score_grid, one_x_two, markets, blend,
                           load_matches, grid_cells, cell_of, poisson_row,
                           SPLIT, BLEND_W, MAX_GOALS)

P = params()


class TestScoreGrid(unittest.TestCase):
    def test_grid_sums_to_one(self):
        g = score_grid(1.5, 1.1, P["rho"])
        self.assertAlmostEqual(sum(map(sum, g)), 1.0, places=9)

    def test_dixon_coles_direction(self):
        """Negative rho must raise 0-0 and 1-1, cut 1-0 and 0-1."""
        plain = score_grid(1.3, 1.2, 0.0)
        dc = score_grid(1.3, 1.2, -0.10)
        self.assertGreater(dc[0][0] / dc[1][0], plain[0][0] / plain[1][0])
        self.assertGreater(dc[1][1] / dc[0][1], plain[1][1] / plain[0][1])

    def test_one_x_two_sums(self):
        pH, pD, pA = one_x_two(score_grid(2.0, 0.7, P["rho"]))
        self.assertAlmostEqual(pH + pD + pA, 1.0, places=9)
        self.assertGreater(pH, pA)   # stronger attack should be favourite

    def test_totals_monotonic(self):
        _, _, _, totals, btts, spread, scores = markets(
            score_grid(1.6, 1.2, P["rho"]))
        self.assertGreaterEqual(totals["over_1.5"], totals["over_2.5"])
        self.assertGreaterEqual(totals["over_2.5"], totals["over_3.5"])
        self.assertTrue(0 <= btts <= 1)
        self.assertGreaterEqual(spread["home_-1.5"], 0)
        self.assertEqual(len(scores), 5)

    def test_home_advantage_symmetry(self):
        """Swapping lambdas must mirror the 1X2."""
        a = one_x_two(score_grid(1.8, 0.9, P["rho"]))
        b = one_x_two(score_grid(0.9, 1.8, P["rho"]))
        self.assertAlmostEqual(a[0], b[2], places=9)
        self.assertAlmostEqual(a[1], b[1], places=9)


class TestExactScores(unittest.TestCase):
    def test_grid_cells_shape_and_sum(self):
        cells = grid_cells(score_grid(1.5, 1.1, P["rho"]))
        self.assertEqual(len(cells), 17)   # 0-0..3-3 + other
        self.assertAlmostEqual(sum(cells.values()), 1.0, places=9)
        self.assertGreater(cells["other"], 0)

    def test_cell_of(self):
        self.assertEqual(cell_of(2, 1), "2-1")
        self.assertEqual(cell_of(3, 3), "3-3")
        self.assertEqual(cell_of(4, 0), "other")
        self.assertEqual(cell_of(0, 5), "other")

    def test_boost_direction(self):
        """min2_boost > 1 must raise both-score-2+ cells, sum stays 1."""
        plain = score_grid(1.4, 1.3, P["rho"])
        boosted = score_grid(1.4, 1.3, P["rho"], 1.3)
        self.assertAlmostEqual(sum(map(sum, boosted)), 1.0, places=9)
        self.assertGreater(boosted[2][2] / boosted[1][1],
                           plain[2][2] / plain[1][1])
        self.assertLess(boosted[1][0], plain[1][0])   # renormalisation

    def test_boost_one_is_identity(self):
        a = score_grid(1.4, 1.3, P["rho"])
        b = score_grid(1.4, 1.3, P["rho"], 1.0)
        self.assertEqual(a, b)

    def test_default_param_present(self):
        self.assertIn("min2_boost", P)
        self.assertGreaterEqual(P["min2_boost"], 1.0)


class TestPoissonRow(unittest.TestCase):
    def test_row_sums_to_one(self):
        """Truncated at MAX_GOALS, so the tail loss must stay negligible."""
        for lam in (0.3, 1.5, 4.0):
            self.assertAlmostEqual(sum(poisson_row(lam)), 1.0, places=3)

    def test_row_length(self):
        self.assertEqual(len(poisson_row(1.0)), MAX_GOALS + 1)

    def test_mode_near_lambda(self):
        row = poisson_row(2.0)
        self.assertIn(row.index(max(row)), (1, 2))


class TestBlend(unittest.TestCase):
    MODEL = {"home": 0.5, "draw": 0.3, "away": 0.2}
    MARKET = {"home": 0.7, "draw": 0.2, "away": 0.15}   # overround on purpose

    def test_blend_normalises(self):
        out = blend(self.MODEL, self.MARKET)
        self.assertAlmostEqual(sum(out.values()), 1.0, places=9)

    def test_blend_between_sources(self):
        out = blend(self.MODEL, self.MARKET)
        mkt_norm = 0.7 / 1.05
        self.assertTrue(min(0.5, mkt_norm) < out["home"] < max(0.5, mkt_norm))

    def test_zero_weight_returns_model(self):
        out = blend(self.MODEL, self.MARKET, w=0)
        self.assertAlmostEqual(out["home"], 0.5, places=9)

    def test_weight_constant_sane(self):
        self.assertTrue(0 < BLEND_W < 1)

    def test_full_weight_returns_market(self):
        out = blend(self.MODEL, self.MARKET, w=1)
        self.assertAlmostEqual(out["home"], 0.7 / 1.05, places=9)


class TestDataPatches(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.matches = load_matches("2026-06-09", P["half_life"],
                                   P["friendly_w"], P["margin_cap"])

    def find(self, home, away, date_after="2026-01-01"):
        return [m for m in self.matches if m["home"] == home and
                m["away"] == away]

    def test_score_fixes_applied(self):
        jam = [m for m in self.find("Jamaica", "South Africa")
               if (m["hg"], m["ag"]) == (1, 1)]
        self.assertTrue(jam, "Jamaica 1-1 South Africa fix missing")
        ber = [m for m in self.find("Bermuda", "Cape Verde")
               if (m["hg"], m["ag"]) == (0, 3)]
        self.assertTrue(ber, "Bermuda 0-3 Cape Verde fix missing")

    def test_additions_present(self):
        self.assertTrue(self.find("Canada", "Guatemala"))
        self.assertTrue(self.find("Tajikistan", "Iran"))

    def test_weights_positive_and_capped(self):
        self.assertTrue(all(0 < m["w"] <= 1 for m in self.matches))


if __name__ == "__main__":
    unittest.main()
