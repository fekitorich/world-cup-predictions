"""Unit: the news-gate logic. The LLM is absent here on purpose — these
tests prove the code-side contract: reduce-only application, strict
report validation, fail-open (unchanged plan) semantics, and the
advisory lambda adjustment math."""
import json
import os
import sys
import tempfile
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

import betting.news_check as nc


def bet(name="b1", stake=5.0):
    return {"bet": name, "stake_usdc": stake, "category": "moneyline"}


class TestValidateReport(unittest.TestCase):
    def test_unknown_bets_dropped_known_kept(self):
        rep = {"flags": [
            {"bet": "ours", "flag": "veto", "reasons": ["star out (BBC)"]},
            {"bet": "invented by the llm", "flag": "veto", "reasons": ["x"]}]}
        fm = nc.validate_report(rep, ["ours", "other"])
        self.assertEqual(fm["ours"][0], "veto")
        self.assertEqual(fm["other"], ("clear", []))   # ignored -> default
        self.assertNotIn("invented by the llm", fm)

    def test_invalid_flag_becomes_safe_default(self):
        rep = {"flags": [{"bet": "ours", "flag": "double-down!!"}]}
        self.assertEqual(nc.validate_report(rep, ["ours"])["ours"][0],
                         "clear")

    def test_holdings_mode_defaults_to_hold(self):
        fm = nc.validate_report({}, ["pos"], flags=nc.HOLD_FLAGS)
        self.assertEqual(fm["pos"], ("hold", []))

    def test_junk_report_harmless(self):
        self.assertEqual(nc.validate_report(None, ["a"])["a"], ("clear", []))


class TestApplyFlags(unittest.TestCase):
    CFG = {"news_caution_factor": 0.5}

    def test_veto_removes(self):
        kept, dropped, _ = nc.apply_flags(
            [bet("a"), bet("b")], {"a": ("veto", ["out"])}, self.CFG)
        self.assertEqual([b["bet"] for b in kept], ["b"])
        self.assertEqual(dropped[0]["news_reasons"], ["out"])

    def test_caution_halves_stake(self):
        kept, _, scaled = nc.apply_flags(
            [bet("a", 6.0)], {"a": ("caution", ["doubtful"])}, self.CFG)
        self.assertEqual(kept[0]["stake_usdc"], 3.0)
        self.assertEqual(scaled, ["a"])

    def test_caution_below_dollar_drops(self):
        kept, dropped, _ = nc.apply_flags(
            [bet("a", 1.5)], {"a": ("caution", [])}, self.CFG)
        self.assertEqual(kept, [])
        self.assertEqual(len(dropped), 1)

    def test_reduce_only_no_flag_no_change(self):
        original = bet("a", 7.0)
        kept, dropped, scaled = nc.apply_flags([dict(original)], {}, self.CFG)
        self.assertEqual(kept[0]["stake_usdc"], 7.0)
        self.assertEqual((dropped, scaled), ([], []))

    def test_clear_flag_changes_nothing(self):
        kept, _, _ = nc.apply_flags(
            [bet("a", 7.0)], {"a": ("clear", [])}, self.CFG)
        self.assertEqual(kept[0]["stake_usdc"], 7.0)
        self.assertNotIn("news_flag", kept[0])


class TestExtractJson(unittest.TestCase):
    def test_json_amid_prose(self):
        obj = nc.extract_json('Here you go:\n{"flags": [], "summary": "ok"}')
        self.assertEqual(obj["summary"], "ok")

    def test_no_json_raises(self):
        with self.assertRaises(ValueError):
            nc.extract_json("I could not find anything relevant.")


class TestAdjustmentMath(unittest.TestCase):
    XG = {"home": 1.8, "away": 0.9}

    def test_adjusted_moneyline_shifts_toward_opponent(self):
        base = nc.adjusted_moneyline(self.XG)
        adj = nc.adjusted_moneyline(self.XG, scale_home=0.7)
        self.assertLess(adj["home"], base["home"])
        self.assertGreater(adj["away"], base["away"])
        self.assertAlmostEqual(sum(adj.values()), 1.0, places=2)

    def test_noop_scale_is_identity(self):
        self.assertEqual(nc.adjusted_moneyline(self.XG),
                         nc.adjusted_moneyline(self.XG, 1.0, 1.0))


class TestGoalShareAndAdvisories(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        json.dump({"squads": {"Mexico": [
            {"name": "R. Jiménez", "goals": 8},
            {"name": "S. Giménez", "goals": 2}]}},
            open(os.path.join(self.tmp.name, "wc26_players.json"), "w"))
        self.saved = nc.DATA
        nc.DATA = self.tmp.name

    def tearDown(self):
        nc.DATA = self.saved
        self.tmp.cleanup()

    def test_goal_share_by_surname(self):
        self.assertAlmostEqual(nc.goal_share("Mexico", "Raul Jiménez"), 0.8)
        self.assertEqual(nc.goal_share("Mexico", "Unknown Player"), 0.0)
        self.assertEqual(nc.goal_share("Atlantis", "Anyone"), 0.0)

    def test_confirmed_absence_produces_advisory(self):
        sim = {"home": "Mexico", "away": "Canada",
               "xg": {"home": 1.8, "away": 0.9},
               "moneyline": {"home": 0.6, "draw": 0.25, "away": 0.15}}
        rep = {"key_absences": [
            {"team": "Mexico", "player": "R. Jiménez",
             "status": "confirmed"},
            {"team": "Mexico", "player": "S. Giménez",
             "status": "doubtful"}]}    # doubtful never adjusts
        adv = nc.absence_advisories(rep, sim)
        self.assertEqual(len(adv), 1)
        self.assertLess(adv[0]["moneyline_adjusted"]["home"],
                        sim["moneyline"]["home"])


if __name__ == "__main__":
    unittest.main()
