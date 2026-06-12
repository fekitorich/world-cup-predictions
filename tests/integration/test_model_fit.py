"""Integration: the Dixon-Coles fitting loop end to end on a synthetic
league with a known pecking order. If the optimizer, the rating
normalization or the home-advantage estimate drift, this fails before
any real prediction does."""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

from wc26_simulate import fit, lambdas, one_x_two, score_grid


def m(home, away, hg, ag, neutral=False, w=1.0):
    return {"home": home, "away": away, "hg": hg, "ag": ag,
            "neutral": neutral, "w": w}


def synthetic_league():
    """Strong > Mid > Weak, played home and away, several rounds.
    Home sides get a goal of help so hadv has something to find."""
    rounds = []
    for _ in range(8):
        rounds += [
            m("Strong", "Weak", 4, 0), m("Weak", "Strong", 1, 2),
            m("Strong", "Mid", 3, 1), m("Mid", "Strong", 1, 1),
            m("Mid", "Weak", 3, 1), m("Weak", "Mid", 1, 1),
        ]
    return rounds


class TestFit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # value_beta=0: synthetic teams have no squad value; the prior
        # must stay out of this fit entirely
        cls.model = fit(synthetic_league(), shrink=2.0, value_beta=0.0)

    def test_rating_order_matches_results(self):
        att = self.model["att"]
        self.assertGreater(att["Strong"], att["Mid"])
        self.assertGreater(att["Mid"], att["Weak"])
        dfn = self.model["dfn"]   # conceding more = a higher (worse) dfn
        self.assertLess(dfn["Strong"], dfn["Weak"])

    def test_ratings_are_centered(self):
        for key in ("att", "dfn"):
            vals = self.model[key].values()
            self.assertAlmostEqual(sum(vals) / len(vals), 0.0, places=6)

    def test_home_advantage_positive(self):
        self.assertGreater(self.model["hadv"], 0.0)

    def test_lambdas_favor_the_stronger_side(self):
        l1, l2 = lambdas(self.model, "Strong", "Weak", home_field=False)
        self.assertGreater(l1, l2)
        ln1, _ = lambdas(self.model, "Strong", "Weak", home_field=True)
        self.assertGreater(ln1, l1)   # home field adds goals

    def test_fit_feeds_a_sane_grid(self):
        l1, l2 = lambdas(self.model, "Strong", "Weak", home_field=False)
        probs = one_x_two(score_grid(l1, l2, rho=-0.08))
        h, d, a = probs
        self.assertAlmostEqual(h + d + a, 1.0, places=2)
        self.assertGreater(h, a)   # the favourite is the favourite


if __name__ == "__main__":
    unittest.main()
