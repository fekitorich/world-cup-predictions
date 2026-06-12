"""Unit: the negative-binomial machinery behind the corners model."""
import math
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

from wc26_corners import nb_logpmf, nb_cdf_over, fit_nb


class TestNegBin(unittest.TestCase):
    MU, K = 9.18, 21.0

    def test_pmf_is_a_distribution(self):
        total = sum(math.exp(nb_logpmf(y, self.MU, self.K)) for y in range(200))
        self.assertAlmostEqual(total, 1.0, places=9)

    def test_pmf_mean_is_mu(self):
        mean = sum(y * math.exp(nb_logpmf(y, self.MU, self.K))
                   for y in range(200))
        self.assertAlmostEqual(mean, self.MU, places=6)

    def test_overdispersion_vs_poisson(self):
        """NegBin variance is mu + mu^2/k — strictly above Poisson's mu."""
        var = sum((y - self.MU) ** 2 * math.exp(nb_logpmf(y, self.MU, self.K))
                  for y in range(220))
        self.assertAlmostEqual(var, self.MU + self.MU ** 2 / self.K, places=4)

    def test_cdf_over_complements_pmf(self):
        over = nb_cdf_over(9.5, self.MU, self.K)
        under = sum(math.exp(nb_logpmf(y, self.MU, self.K)) for y in range(10))
        self.assertAlmostEqual(over + under, 1.0, places=9)

    def test_cdf_over_monotone_in_line(self):
        probs = [nb_cdf_over(line + 0.5, self.MU, self.K)
                 for line in range(6, 14)]
        self.assertEqual(probs, sorted(probs, reverse=True))


class TestFitNB(unittest.TestCase):
    def test_intercept_only_recovers_mean(self):
        data = [{"y": y, "xg": 2.5} for y in (7, 8, 9, 10, 11) * 20]
        a, b, k, mean_x, ll = fit_nb(data, b_fixed=0.0)
        self.assertAlmostEqual(math.exp(a), 9.0, delta=0.2)
        self.assertEqual(b, 0.0)
        self.assertGreater(k, 0.5)
        self.assertTrue(math.isfinite(ll))


if __name__ == "__main__":
    unittest.main()
