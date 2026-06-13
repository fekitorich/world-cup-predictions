"""Unit: the personal betting report's grading/aggregation math.
No network — markets are supplied directly."""
import json
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from betting.report import grade, totals, entry_price, render, cfg


def mk(prices, closed=False):
    return {"outcomePrices": json.dumps([str(p) for p in prices]),
            "closed": closed}


def bet(tok, stake, entry, cat="moneyline", **extra):
    return {"bet": f"b-{tok}", "token_id": tok, "stake_usdc": stake,
            "price_at_exec": entry, "category": cat, **extra}


class TestEntryPrice(unittest.TestCase):
    def test_prefers_executed_then_seen_then_market(self):
        self.assertEqual(entry_price({"price_at_exec": 0.3, "price_seen": 0.4}),
                         0.3)
        self.assertEqual(entry_price({"price_seen": 0.4}), 0.4)
        self.assertEqual(entry_price({"market_p": 0.5}), 0.5)


class TestGrade(unittest.TestCase):
    LEDGER = {"placed": [
        bet("win", 5.0, 0.25),        # resolved winner
        bet("lose", 4.0, 0.40),       # resolved loser
        bet("open", 2.0, 0.50, cat="totals"),   # open, drifted up
        bet("gone", 3.0, 0.30),       # no live price
    ]}
    MARKETS = {
        "win": (mk(["0.99", "0.01"], closed=True), 0),
        "lose": (mk(["0.01", "0.99"], closed=True), 0),
        "open": (mk(["0.60", "0.40"]), 0),
        # "gone" deliberately absent
    }

    def setUp(self):
        self.rows = grade(self.LEDGER, self.MARKETS)
        self.by = {r["bet"]: r for r in self.rows}

    def test_winner_pnl_is_inverse_odds(self):
        r = self.by["b-win"]
        self.assertEqual(r["status"], "won")
        self.assertAlmostEqual(r["pnl"], 5.0 / 0.25 - 5.0)   # shares - stake

    def test_loser_loses_stake(self):
        r = self.by["b-lose"]
        self.assertEqual(r["status"], "lost")
        self.assertAlmostEqual(r["pnl"], -4.0)

    def test_open_marked_to_market(self):
        r = self.by["b-open"]
        self.assertEqual(r["status"], "open")
        self.assertAlmostEqual(r["clv"], 0.10)            # 0.60 - 0.50
        self.assertAlmostEqual(r["value"], (2.0 / 0.50) * 0.60)
        self.assertAlmostEqual(r["pnl"], r["value"] - 2.0)

    def test_missing_market_left_unpriced(self):
        r = self.by["b-gone"]
        self.assertIsNone(r["cur"])
        self.assertEqual(r["status"], "open")
        self.assertEqual(r["value"], 3.0)   # falls back to stake, no fake P&L


class TestTotals(unittest.TestCase):
    def setUp(self):
        rows = grade(TestGrade.LEDGER, TestGrade.MARKETS)
        self.agg, self.cats = totals(rows)

    def test_aggregate_counts(self):
        self.assertAlmostEqual(self.agg["deployed"], 14.0)
        self.assertEqual((self.agg["won"], self.agg["lost"]), (1, 1))
        self.assertEqual(self.agg["open_n"], 1)      # the priced open one
        self.assertEqual(self.agg["unknown"], 1)     # the unpriced one

    def test_resolved_pnl_nets_win_and_loss(self):
        self.assertAlmostEqual(self.agg["resolved_pnl"],
                               (5.0 / 0.25 - 5.0) - 4.0)

    def test_category_split(self):
        self.assertIn("totals", self.cats)
        self.assertEqual(self.cats["totals"]["n"], 1)


class TestRenderSmoke(unittest.TestCase):
    def test_renders_and_escapes(self):
        ledger = {"placed": [bet("x", 5.0, 0.25, bet_name="<script>")]}
        ledger["placed"][0]["bet"] = "a <script> b"
        rows = grade(ledger, {"x": (mk(["0.9", "0.1"], closed=True), 0)})
        agg, cats = totals(rows)
        page = render(rows, agg, cats, {"max_total_stake_usdc": 100},
                      None, None)
        self.assertIn("Betting report", page)
        self.assertIn("local only", page)
        self.assertNotIn("<script>", page)

    def test_empty_ledger_safe(self):
        rows = grade({"placed": []}, {})
        agg, cats = totals(rows)
        page = render(rows, agg, cats, {"max_total_stake_usdc": 100}, None, None)
        self.assertIn("Betting report", page)


if __name__ == "__main__":
    unittest.main()
