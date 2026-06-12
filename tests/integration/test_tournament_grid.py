"""Integration: the tournament engine's numpy score grid must agree with
the stdlib model's grid — two implementations of the same Dixon-Coles
math that must never drift apart. Skips where numpy isn't installed
(the gate runs on system python; coverage runs use the venv)."""
import importlib.util
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

HAVE_NUMPY = importlib.util.find_spec("numpy") is not None


@unittest.skipUnless(HAVE_NUMPY, "numpy not installed (system python)")
class TestGridParity(unittest.TestCase):
    CASES = [(1.4, 1.1, -0.08, 1.0), (2.3, 0.4, -0.08, 1.0),
             (0.9, 0.9, -0.12, 1.1)]

    def test_numpy_grid_matches_stdlib_grid(self):
        import wc26_tournament as T
        from wc26_simulate import score_grid

        def normalized(g):
            tot = sum(sum(row) for row in g)
            return [[c / tot for c in row] for row in g]

        for l1, l2, rho, boost in self.CASES:
            a = normalized(score_grid(l1, l2, rho, boost))
            b = normalized(T.grid_np(l1, l2, rho, boost).tolist())
            for i in range(6):
                for j in range(6):
                    self.assertAlmostEqual(
                        a[i][j], b[i][j], places=6,
                        msg=f"cell {i}-{j} for lams {l1}/{l2}")


if __name__ == "__main__":
    unittest.main()
