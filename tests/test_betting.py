"""Betting math and safety invariants (no network, no keys, no orders)."""
import json
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

from betting.find_bets import kelly_stake, started, build_plan, CFG
from wc26_polymarket import parse_score_question


def cand(category, edge, model_p=None, market_p=0.30):
    return {"category": category, "bet": f"{category}@{edge}",
            "question": "?", "token_id": "t",
            "model_p": model_p if model_p is not None else market_p + edge,
            "market_p": market_p, "edge": edge}


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


class TestBuildPlan(unittest.TestCase):
    CFG = {"max_total_stake_usdc": 100.0, "max_per_bet_usdc": 10.0,
           "kelly_fraction": 0.4, "min_stake_usdc": 1.0, "max_bets": 3}

    def test_awards_always_make_the_plan(self):
        cands = [cand("moneyline", 0.20), cand("moneyline", 0.18),
                 cand("moneyline", 0.15), cand("golden_boot", 0.04)]
        plan, _ = build_plan(cands, self.CFG)
        cats = [c["category"] for c in plan]
        self.assertIn("golden_boot", cats)
        self.assertEqual(len(plan), 3)   # max_bets, award kept a slot

    def test_per_match_slots_filled_by_edge(self):
        cands = [cand("moneyline", e) for e in (0.10, 0.30, 0.20)] + \
                [cand("exact_score", 0.25)]
        plan, _ = build_plan(cands, self.CFG)
        self.assertEqual([c["edge"] for c in plan], [0.30, 0.25, 0.20])

    def test_per_bet_cap_respected(self):
        plan, _ = build_plan([cand("moneyline", 0.40, market_p=0.10)],
                             self.CFG)
        self.assertLessEqual(plan[0]["stake_usdc"],
                             self.CFG["max_per_bet_usdc"])

    def test_min_stake_floor(self):
        plan, _ = build_plan([cand("moneyline", 0.005, market_p=0.50)],
                             self.CFG)
        self.assertGreaterEqual(plan[0]["stake_usdc"],
                                self.CFG["min_stake_usdc"])

    def test_total_cap_scaling(self):
        cfg = dict(self.CFG, max_bets=40, max_total_stake_usdc=20.0)
        cands = [cand("moneyline", 0.30, market_p=0.10) for _ in range(20)]
        plan, total = build_plan(cands, cfg)
        self.assertLessEqual(total, 20.0 + 0.05)
        self.assertEqual(len(plan), 20)

    def test_empty_plan(self):
        plan, total = build_plan([], self.CFG)
        self.assertEqual((plan, total), ([], 0.0))


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
