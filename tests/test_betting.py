"""Betting math and safety invariants (no network, no keys, no orders)."""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from betting.find_bets import kelly_stake, started, CFG
from wc26_polymarket import parse_score_question


class TestKelly(unittest.TestCase):
    def test_kelly_zero_at_fair_price(self):
        self.assertAlmostEqual(kelly_stake(0.4, 0.4, 100), 0.0, places=9)

    def test_kelly_positive_with_edge(self):
        self.assertGreater(kelly_stake(0.5, 0.3, 100), 0)

    def test_kelly_scales_with_bankroll(self):
        self.assertAlmostEqual(kelly_stake(0.5, 0.3, 200),
                               2 * kelly_stake(0.5, 0.3, 100), places=9)

    def test_kelly_fraction_is_fractional(self):
        """Full Kelly for q=.5, p=.3 is f*=2/7 of bankroll; ours must be less."""
        self.assertLess(kelly_stake(0.5, 0.3, 100), 100 * (0.5 - 0.3) / 0.7)


class TestConfig(unittest.TestCase):
    def test_caps_sane(self):
        self.assertGreater(CFG["max_total_stake_usdc"], 0)
        self.assertGreater(CFG["max_per_bet_usdc"], 0)
        self.assertLessEqual(CFG["max_per_bet_usdc"],
                             CFG["max_total_stake_usdc"])
        self.assertTrue(0 < CFG["kelly_fraction"] <= 1)
        self.assertTrue(0 < CFG["min_edge_match"] < 0.5)


class TestExactScoreScanner(unittest.TestCase):
    def test_parse_home_first(self):
        self.assertEqual(parse_score_question(
            "Exact Score: Mexico 2 - 1 South Africa?",
            "Mexico", "South Africa"), "2-1")

    def test_parse_away_named_first(self):
        self.assertEqual(parse_score_question(
            "Exact Score: South Africa 2 - 1 Mexico?",
            "Mexico", "South Africa"), "1-2")

    def test_parse_aliases(self):
        self.assertEqual(parse_score_question(
            "Exact Score: Türkiye 1 - 0 Paraguay?",
            "Turkey", "Paraguay"), "1-0")

    def test_parse_other_and_junk(self):
        self.assertEqual(parse_score_question(
            "Exact Score: Any Other Score?", "Mexico", "South Africa"),
            "other")
        self.assertIsNone(parse_score_question(
            "Will Mexico win on 2026-06-11?", "Mexico", "South Africa"))

    def test_started_guard(self):
        times = {"1": "2000-01-01T12:00:00+00:00",
                 "2": "2099-01-01T12:00:00+00:00"}
        self.assertTrue(started("1", times))
        self.assertFalse(started("2", times))
        self.assertFalse(started("3", times))   # unknown id: no guard claim

    def test_exact_score_ships_disabled(self):
        """Committed config must keep exact_score off; enabling is a local,
        deliberate opt-in (config.local.json)."""
        committed = json.load(open(os.path.join(ROOT, "betting", "config.json")))
        self.assertIs(committed["include"]["exact_score"], False)
        self.assertGreaterEqual(committed["min_edge_score"],
                                committed["min_edge_match"])


class TestLedgerInvariants(unittest.TestCase):
    """Run only where the (gitignored) ledger exists - i.e. on this machine."""
    LEDGER = os.path.join(ROOT, "betting", "state", "ledger.json")

    @unittest.skipUnless(os.path.exists(LEDGER), "no local ledger")
    def test_ledger_respects_caps(self):
        led = json.load(open(self.LEDGER))["placed"]
        total = sum(b["stake_usdc"] for b in led)
        self.assertLessEqual(total, CFG["max_total_stake_usdc"] + 0.01)
        for b in led:
            self.assertLessEqual(b["stake_usdc"],
                                 25.01,  # historical per-bet cap high-water
                                 b["bet"])

    @unittest.skipUnless(os.path.exists(LEDGER), "no local ledger")
    def test_no_duplicate_positions(self):
        led = json.load(open(self.LEDGER))["placed"]
        tokens = [b["token_id"] for b in led]
        self.assertEqual(len(tokens), len(set(tokens)))


if __name__ == "__main__":
    unittest.main()
