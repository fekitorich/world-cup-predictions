"""Unit: paper-trading scoreboard aggregation (CLV + resolved PnL)."""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from betting.paper import first_seen, aggregate


def market(prices, closed=False):
    return {"outcomePrices": str(prices).replace("'", '"'), "closed": closed}


class TestFirstSeen(unittest.TestCase):
    def test_first_sighting_wins(self):
        runs = [
            {"at": "t1", "candidates": [
                {"token_id": "a", "category": "moneyline", "market_p": 0.50}]},
            {"at": "t2", "candidates": [
                {"token_id": "a", "category": "moneyline", "market_p": 0.60},
                {"token_id": "b", "category": "corners", "market_p": 0.40}]},
        ]
        first = first_seen(runs)
        self.assertEqual(first["a"]["market_p"], 0.50)   # entry = first look
        self.assertEqual(first["a"]["at"], "t1")
        self.assertEqual(first["b"]["at"], "t2")


class TestAggregate(unittest.TestCase):
    def test_clv_open_market(self):
        first = {"a": {"category": "moneyline", "market_p": 0.50}}
        cats = aggregate(first, {"a": (market(["0.62", "0.38"]), 0)})
        st = cats["moneyline"]
        self.assertEqual(st["n"], 1)
        self.assertAlmostEqual(st["clv"], 0.12)
        self.assertEqual(st["resolved"], 0)

    def test_resolved_win_pays_inverse_odds(self):
        first = {"a": {"category": "futures", "market_p": 0.25}}
        cats = aggregate(first, {"a": (market(["1", "0"], closed=True), 0)})
        st = cats["futures"]
        self.assertEqual((st["resolved"], st["wins"]), (1, 1))
        self.assertAlmostEqual(st["pnl"], 1 / 0.25 - 1)   # flat $1 stake

    def test_resolved_loss_costs_the_dollar(self):
        first = {"a": {"category": "totals", "market_p": 0.40}}
        cats = aggregate(first, {"a": (market(["0", "1"], closed=True), 0)})
        self.assertAlmostEqual(cats["totals"]["pnl"], -1.0)

    def test_second_outcome_index_used(self):
        """A NO-side paper position must read the second outcome price."""
        first = {"a": {"category": "btts", "market_p": 0.55}}
        cats = aggregate(first, {"a": (market(["0.30", "0.70"]), 1)})
        self.assertAlmostEqual(cats["btts"]["clv"], 0.15)

    def test_unknown_or_junk_markets_skipped(self):
        first = {"a": {"category": "moneyline", "market_p": 0.5},
                 "b": {"category": "moneyline", "market_p": 0.5}}
        cats = aggregate(first, {"b": ({"outcomePrices": "junk"}, 0)})
        self.assertEqual(cats, {})


if __name__ == "__main__":
    unittest.main()
