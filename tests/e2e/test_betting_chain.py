"""E2E: the whole betting brain offline — synthetic data files + a faked
Gamma API drive every scanner, the plan builder and the execution filter
end to end. No network, no keys, no orders; this is the test that proves
"run it" does the right thing before any of it touches money."""
import json
import os
import sys
import tempfile
import types
import unittest
import io
from contextlib import redirect_stdout

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

import betting.find_bets as fb
from betting.place_bets import select_todo

FUTURE = "2099-01-01T18:00:00+00:00"
PAST = "2000-01-01T18:00:00+00:00"


def mk(question, yes, no=None, liq=5000, spread=0.02, tok="tok",
       outcomes=("Yes", "No")):
    no = round(1 - yes, 4) if no is None else no
    return {"question": question,
            "outcomePrices": json.dumps([str(yes), str(no)]),
            "clobTokenIds": json.dumps([f"{tok}-y", f"{tok}-n"]),
            "outcomes": json.dumps(list(outcomes)),
            "negRisk": "Will " in question,   # mimic: 3-ways neg-risk,
            "liquidityNum": liq, "spread": spread}   # binaries not


def sim(home, away):
    return {
        "home": home, "away": away,
        "moneyline": {"home": 0.60, "draw": 0.25, "away": 0.15},
        "exact_scores": {"2-1": 0.18, "other": 0.82},
        "totals": {"over_2.5": 0.55},
        "team_totals": {"home": {"over_1.5": 0.50},
                        "away": {"over_1.5": 0.10}},
        "btts": 0.60,
        "spread": {"home_-1.5": 0.30, "away_-1.5": 0.05},
        "halftime": {"home": 0.50, "draw": 0.35, "away": 0.15},
        "second_half": {"home": 0.52, "draw": 0.33, "away": 0.15},
        "first_to_score": {"home": 0.60, "away": 0.30, "neither": 0.10},
    }


def match_books(home, away, suffix=""):
    """Every sibling book for one fixture, with deliberate edges and one
    illiquid trap (a fat fake edge behind no liquidity)."""
    t = f"{home[:3]}{suffix}".lower()
    return {
        f"{t}-base": {"markets": [
            mk(f"Will {home} win on 2026-06-20?", 0.40, tok=f"{t}-h"),
            mk(f"Will {home} vs. {away} end in a draw?", 0.30, tok=f"{t}-d"),
            # the trap: huge "edge" (model 0.15 vs 0.01) but a dead book
            mk(f"Will {away} win on 2026-06-20?", 0.01, liq=10, spread=0.5,
               tok=f"{t}-a"),
        ]},
        f"{t}-exact": {"markets": [
            mk(f"Exact Score: {home} 2 - 1 {away}?", 0.05, tok=f"{t}-x21"),
        ]},
        f"{t}-more": {"markets": [
            mk(f"{home} vs. {away}: O/U 2.5", 0.40, tok=f"{t}-ou",
               outcomes=("Over", "Under")),
            mk(f"{home} vs. {away}: {home} O/U 1.5", 0.30, tok=f"{t}-tt",
               outcomes=("Over", "Under")),
            mk(f"{home} vs. {away}: Both Teams to Score", 0.45, tok=f"{t}-btts"),
        ]},
        f"{t}-ht": {"markets": [
            mk(f"Will {home} win the first half?", 0.30, tok=f"{t}-ht")]},
        f"{t}-2h": {"markets": [
            mk(f"Will {home} win the second half?", 0.32, tok=f"{t}-2h")]},
        f"{t}-fts": {"markets": [
            mk(f"{home} to score first?", 0.45, tok=f"{t}-fts")]},
        f"{t}-corners": {"markets": [
            mk(f"{home} vs. {away}: O/U 9.5 Total Corners?", 0.25,
               tok=f"{t}-cor", outcomes=("Over", "Under"))]},
    }


class TestBettingChain(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        slugs = lambda t: {   # noqa: E731
            "slug": f"{t}-base", "exact_score_slug": f"{t}-exact",
            "more_markets_slug": f"{t}-more", "halftime_slug": f"{t}-ht",
            "second_half_slug": f"{t}-2h", "first_to_score_slug": f"{t}-fts",
            "corners_slug": f"{t}-corners"}
        dump = lambda name, obj: json.dump(   # noqa: E731
            obj, open(os.path.join(d, name), "w"))
        dump("fifa_world_cup_2026_group_matches.json", {"matches": [
            {"match_id": 101, "date_utc": FUTURE},
            {"match_id": 102, "date_utc": PAST}]})
        dump("wc26_simulations.json", {"simulations": {
            "101": sim("Mexico", "Canada"),
            "102": sim("Japan", "Sweden")}})
        dump("wc26_market_prices.json", {"prices": {
            "101": slugs("mex"), "102": slugs("jap")}})
        dump("wc26_corners.json", {"matches": {
            "101": {"over_9.5": 0.43}, "102": {"over_9.5": 0.43}}})
        dump("wc26_tournament.json", {"teams": {
            "Mexico": {"champion": 0.10, "r32": 0.90},
            "Canada": {"champion": 0.02, "r32": 0.85}}})
        dump("wc26_awards.json", {
            "golden_boot": [{"player": "H. Kane", "p_model": 0.20}],
            "top_scorer_nation": [{"team": "England", "p_model": 0.15}]})

        cls.events = {}
        cls.events.update(match_books("Mexico", "Canada"))
        cls.events.update(match_books("Japan", "Sweden"))   # started match
        cls.events["world-cup-winner"] = {"markets": [
            mk("Will Mexico win the 2026 World Cup?", 0.04, tok="fut-mex",
               liq=50000) | {"groupItemTitle": "Mexico"}]}
        cls.events[fb.AWARD_SLUGS["golden_boot"]] = {"markets": [
            mk("Will Harry Kane win the Golden Boot?", 0.12, tok="aw-kane")
            | {"groupItemTitle": "Harry Kane"}]}
        cls.events[fb.AWARD_SLUGS["top_scorer_nation"]] = {"markets": [
            mk("Will England produce the top scorer?", 0.08, tok="aw-eng")
            | {"groupItemTitle": "England"}]}

        cls._saved = (fb.DATA, fb.CFG, fb.time)
        fb.DATA = d
        fb.time = types.SimpleNamespace(sleep=lambda s: None)
        fb.CFG = {
            "max_total_stake_usdc": 100.0, "max_per_bet_usdc": 10.0,
            "kelly_fraction": 0.4, "min_edge_match": 0.05,
            "min_edge_award": 0.03, "min_edge_score": 0.05,
            "min_liquidity_usdc": 1000, "max_book_spread": 0.06,
            "max_bets": 40, "min_stake_usdc": 1.0,
            "max_per_match_usdc": 25.0,
            "include": {k: True for k in (
                "moneyline", "exact_score", "totals", "team_totals", "btts",
                "spread", "halftime", "second_half", "first_to_score",
                "futures", "corners", "golden_boot", "top_scorer_nation")},
        }
        fb.gamma = lambda path, **q: (
            [cls.events[q["slug"]]] if q.get("slug") in cls.events else [])

        with redirect_stdout(io.StringIO()):
            cands = []
            cands += fb.match_candidates()
            cands += fb.exact_score_candidates()
            cands += fb.more_markets_candidates()
            cands += fb.sibling_result_candidates()
            cands += fb.corners_candidates()
            cands += fb.futures_candidates()
            cands += fb.award_candidates()
        cls.cands = cands
        cls.plan, cls.total = fb.build_plan(
            [dict(c) for c in cands], fb.CFG)

    @classmethod
    def tearDownClass(cls):
        fb.DATA, fb.CFG, fb.time = cls._saved
        cls.tmp.cleanup()

    def cats(self):
        return {c["category"] for c in self.cands}

    def test_every_category_produces_a_candidate(self):
        self.assertEqual(self.cats(), {
            "moneyline", "exact_score", "totals", "team_totals", "btts",
            "halftime", "second_half", "first_to_score", "corners",
            "futures", "golden_boot", "top_scorer_nation"})

    def test_started_match_never_scanned(self):
        self.assertFalse([c for c in self.cands
                          if c.get("match_id") == "102"])

    def test_illiquid_trap_rejected(self):
        """Model 0.15 vs price 0.01 looks like +14c — but the book is dead."""
        self.assertFalse([c for c in self.cands if "-a-" in c["token_id"]])

    def test_neg_risk_carried_per_market(self):
        """Order signing needs each book's own negRisk flag — totals are
        binary, moneylines neg-risk; one global default mis-signs half."""
        flavors = {c["neg_risk"] for c in self.cands}
        self.assertEqual(flavors, {True, False})
        for c in self.cands:
            self.assertIn("neg_risk", c, c["bet"])

    def test_edges_honest(self):
        for c in self.cands:
            self.assertAlmostEqual(c["edge"], c["model_p"] - c["market_p"],
                                   places=4, msg=c["bet"])
            self.assertGreater(c["edge"], 0)

    def test_plan_respects_caps(self):
        self.assertLessEqual(self.total, fb.CFG["max_total_stake_usdc"] + 0.05)
        per_match = {}
        for c in self.plan:
            self.assertLessEqual(c["stake_usdc"],
                                 fb.CFG["max_per_bet_usdc"] + 0.01)
            mid = c.get("match_id") or c["bet"]
            per_match[mid] = per_match.get(mid, 0) + c["stake_usdc"]
        for mid, spent in per_match.items():
            self.assertLessEqual(spent, fb.CFG["max_per_match_usdc"] + 0.01,
                                 mid)

    def test_execution_filter_blocks_held_market(self):
        held = self.plan[0]
        ledger = {"placed": [{"token_id": "elsewhere",
                              "question": held["question"],
                              "stake_usdc": 1.0}]}
        times = {"101": FUTURE, "102": PAST}
        with redirect_stdout(io.StringIO()):
            todo = select_todo(self.plan, ledger, fb.CFG, times)
        self.assertNotIn(held["question"], [b["question"] for b in todo])
        self.assertEqual(len(todo), len(self.plan) - 1)


if __name__ == "__main__":
    unittest.main()
