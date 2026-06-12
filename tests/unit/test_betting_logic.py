"""Unit: betting math and safety logic — pure functions only
(no network, no keys, no orders, no repo state)."""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

from betting.find_bets import kelly_stake, started, build_plan, merge_local
from betting.place_bets import plan_age_minutes, exec_price_ok, select_todo
from wc26_polymarket import parse_score_question


def cand(category, edge, model_p=None, market_p=0.30, match_id="m1"):
    return {"category": category, "bet": f"{category}@{edge}",
            "question": "?", "token_id": "t", "match_id": match_id,
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

    def test_per_match_exposure_cap(self):
        """Correlated bets on one fixture must not stack past the cap;
        the highest-edge expressions of the opinion keep their size."""
        cfg = dict(self.CFG, max_bets=40, max_per_match_usdc=12.0)
        cands = [cand(c, e, market_p=0.10, match_id="fix1") for c, e in
                 (("moneyline", 0.40), ("spread", 0.35), ("totals", 0.30),
                  ("team_totals", 0.25), ("halftime", 0.20))] + \
                [cand("moneyline", 0.15, market_p=0.10, match_id="fix2")]
        plan, _ = build_plan(cands, cfg)
        per_match = {}
        for c in plan:
            per_match[c["match_id"]] = \
                per_match.get(c["match_id"], 0) + c["stake_usdc"]
        self.assertLessEqual(per_match["fix1"], 12.0 + 0.01)
        self.assertIn("fix2", per_match)   # other fixtures unaffected
        kept_edges = [c["edge"] for c in plan if c["match_id"] == "fix1"]
        self.assertEqual(kept_edges, sorted(kept_edges, reverse=True))

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

class TestMergeLocal(unittest.TestCase):
    def test_include_deep_merged(self):
        """A local include that flips two gates must not wipe the rest."""
        base = {"max_total_stake_usdc": 20,
                "include": {"moneyline": True, "totals": False,
                            "corners": False}}
        merged = merge_local(dict(base), {"max_total_stake_usdc": 500,
                                          "include": {"totals": True}})
        self.assertEqual(merged["max_total_stake_usdc"], 500)
        self.assertTrue(merged["include"]["moneyline"])   # survived
        self.assertTrue(merged["include"]["totals"])      # flipped
        self.assertFalse(merged["include"]["corners"])    # untouched

    def test_local_without_include(self):
        base = {"include": {"moneyline": True}}
        merged = merge_local(dict(base), {"max_bets": 9})
        self.assertEqual(merged["include"], {"moneyline": True})
        self.assertEqual(merged["max_bets"], 9)


class TestExecutionGuards(unittest.TestCase):
    def test_plan_age(self):
        from datetime import datetime, timezone
        now = datetime(2026, 6, 12, 12, 0, tzinfo=timezone.utc)
        self.assertAlmostEqual(
            plan_age_minutes("2026-06-12 10:30 UTC", now=now), 90.0)

    def test_price_within_band_ok(self):
        ok, _ = exec_price_ok(0.51, 0.50, max_slip=0.02, max_drop=0.10)
        self.assertTrue(ok)

    def test_price_rise_refused(self):
        """The edge was sized at the plan price; pay more and it's gone."""
        ok, why = exec_price_ok(0.53, 0.50, max_slip=0.02, max_drop=0.10)
        self.assertFalse(ok)
        self.assertIn("slippage", why)

    def test_price_collapse_refused(self):
        """A big drop is information we don't have, not a discount."""
        ok, why = exec_price_ok(0.35, 0.50, max_slip=0.02, max_drop=0.10)
        self.assertFalse(ok)
        self.assertIn("information", why)

    def test_small_favorable_drop_ok(self):
        ok, _ = exec_price_ok(0.45, 0.50, max_slip=0.02, max_drop=0.10)
        self.assertTrue(ok)


class TestSelectTodo(unittest.TestCase):
    CFG = {"max_per_bet_usdc": 10.0, "max_total_stake_usdc": 100.0}
    TIMES = {"past": "2000-01-01T12:00:00+00:00",
             "future": "2099-01-01T12:00:00+00:00"}

    @staticmethod
    def bet(token="t1", q="q1", mid="future", stake=5.0):
        return {"token_id": token, "question": q, "match_id": mid,
                "stake_usdc": stake, "bet": f"{token}/{q}"}

    def pick(self, bets, ledger=None, cfg=None):
        import io
        from contextlib import redirect_stdout
        with redirect_stdout(io.StringIO()):
            return select_todo(bets, ledger or {"placed": []},
                               cfg or self.CFG, self.TIMES)

    def test_ledger_token_dedup(self):
        led = {"placed": [{"token_id": "t1", "question": "other",
                           "stake_usdc": 5.0}]}
        self.assertEqual(self.pick([self.bet(token="t1")], led), [])

    def test_ledger_market_dedup_blocks_other_side(self):
        """Holding YES then buying NO of the same market locks in a loss."""
        led = {"placed": [{"token_id": "yes-tok", "question": "q1",
                           "stake_usdc": 5.0}]}
        self.assertEqual(self.pick([self.bet(token="no-tok", q="q1")], led), [])

    def test_in_batch_market_dedup(self):
        """Both sides of one market inside a single plan: only one places."""
        todo = self.pick([self.bet(token="yes-tok", q="q1"),
                          self.bet(token="no-tok", q="q1")])
        self.assertEqual(len(todo), 1)

    def test_kickoff_rechecked_at_execution(self):
        """A plan built pre-kickoff must not execute post-kickoff."""
        todo = self.pick([self.bet(mid="past"),
                          self.bet(token="t2", q="q2", mid="future")])
        self.assertEqual([b["token_id"] for b in todo], ["t2"])

    def test_futures_ids_have_no_kickoff(self):
        todo = self.pick([self.bet(mid="future:Spain")])
        self.assertEqual(len(todo), 1)

    def test_caps_enforced(self):
        led = {"placed": [{"token_id": "x", "question": "qx",
                           "stake_usdc": 95.0}]}
        bets = [self.bet(stake=11.0),                       # > per-bet cap
                self.bet(token="t2", q="q2", stake=6.0)]    # > total cap
        self.assertEqual(self.pick(bets, led), [])


if __name__ == "__main__":
    unittest.main()
