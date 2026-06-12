"""Smoke: the committed configs as checked into the repo. These are the
contracts that protect a fresh clone — placeholder caps, every risky
betting category gated off, freshness rails present."""
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def committed():
    return json.load(open(os.path.join(ROOT, "betting", "config.json")))


class TestCommittedBettingConfig(unittest.TestCase):
    def test_new_categories_ship_disabled(self):
        """Committed config must keep all non-moneyline match categories
        off; enabling is a local, deliberate opt-in (config.local.json)."""
        cfg = committed()
        for cat in ("exact_score", "totals", "team_totals", "btts", "spread",
                    "halftime", "second_half", "first_to_score", "futures",
                    "corners"):
            self.assertIs(cfg["include"][cat], False, cat)
        self.assertGreaterEqual(cfg["min_edge_score"], cfg["min_edge_match"])

    def test_exposure_caps(self):
        cfg = committed()
        self.assertGreater(cfg["max_per_match_usdc"], 0)
        self.assertLessEqual(cfg["max_per_match_usdc"],
                             cfg["max_total_stake_usdc"])

    def test_freshness_rails(self):
        cfg = committed()
        self.assertGreater(cfg["max_plan_age_min"], 0)
        self.assertGreater(cfg["max_price_drop_cents"], 0)
        self.assertGreater(cfg["max_sims_age_hours"], 0)

    def test_lineup_adjustments_ship_advisory_only(self):
        """The news gate may only block/shrink bets out of the box.
        Absence-adjusted moneylines stay advisory until the flag log
        proves them out — flipping this is a deliberate local opt-in."""
        cfg = committed()
        self.assertIs(cfg["apply_lineup_adjustments"], False)
        self.assertTrue(0 < cfg["news_caution_factor"] < 1)
        self.assertGreater(cfg["news_big_edge_cents"], 0)
        self.assertGreater(cfg["news_max_searches"], 0)

    def test_liquidity_filters(self):
        cfg = committed()
        self.assertGreaterEqual(cfg["min_liquidity_usdc"], 100)
        self.assertTrue(0 < cfg["max_book_spread"] <= 0.10)
        self.assertGreater(cfg["max_slippage_cents"], 0)


if __name__ == "__main__":
    unittest.main()
