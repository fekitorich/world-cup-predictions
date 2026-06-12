"""Offline tests for the LLM analyst layer (no network, no API key).

The anthropic SDK is imported lazily inside wc26_llm.client(), so these
tests run under system python without the venv."""
import json
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

import wc26_llm as L
import wc26_build_site as b


class TestGroundingContract(unittest.TestCase):
    def test_system_prompt_demands_grounding(self):
        self.assertIn("ONLY the facts in the dossier", L.SYSTEM)
        self.assertIn("Never add", L.SYSTEM)

    def test_model_is_opus(self):
        self.assertEqual(L.MODEL, "claude-opus-4-8")


class TestPromptBuilders(unittest.TestCase):
    SRC = {"teams": {
        "Mexico": {"fifa_ranking": 14, "confederation": "CONCACAF",
                   "last_10": ["2026-06-05 W 5-1 vs Serbia (H, Friendlies)"],
                   "wiki": "The Mexico national team...",
                   "squad_value_eur_m": 200,
                   "key_players": [{"name": "R. Jiménez", "position": "A",
                                    "intl_goals": 12}]},
        "South Africa": {"fifa_ranking": 60, "confederation": "CAF",
                         "last_10": [], "wiki": "", "squad_value_eur_m": 50,
                         "key_players": []}}}
    M = {"match_id": 1, "home": "Mexico", "away": "South Africa",
         "group": "A", "date_utc": "2026-06-11T19:00:00+00:00",
         "venue": "Estadio Azteca", "city": "Mexico City", "score": "2-0"}
    SIM = {"xg": {"home": 2.1, "away": 0.6},
           "moneyline": {"home": 0.72, "draw": 0.19, "away": 0.09},
           "totals": {"over_2.5": 0.49}, "btts": 0.38,
           "first_to_score": {"home": 0.7, "away": 0.2, "neither": 0.1},
           "halftime": {"home": 0.5, "draw": 0.4, "away": 0.1},
           "top_scores": [{"score": "2-0", "p": 0.13}]}
    MKT = {"moneyline": {"home": 0.865, "draw": 0.115, "away": 0.021}}

    def test_team_prompt_grounded(self):
        p = L.build_team_prompt("Mexico", self.SRC["teams"]["Mexico"],
                                {"champion": 0.012})
        self.assertIn("Serbia", p)
        self.assertIn("champion", p)
        self.assertIn("150-200 words", p)

    def test_preview_prompt_has_both_views(self):
        p = L.build_preview_prompt(self.M, self.SIM, self.MKT, self.SRC)
        self.assertIn("0.72", p)      # model probability
        self.assertIn("0.865", p)     # market price
        self.assertIn("South Africa", p)
        self.assertIn("disagree", p)

    def test_review_prompt_has_result_and_pick(self):
        p = L.build_review_prompt(self.M, self.SIM, self.MKT, self.SRC,
                                  {"pred_score": "1-0", "pred_result": "H",
                                   "hit": True})
        self.assertIn("2-0", p)
        self.assertIn("locked_bracket_pick", p)
        self.assertIn("honestly", p)

    def test_player_prompt(self):
        p = L.build_player_prompt("H. Kane", {"team": "England",
                                              "seasons": {"2025": []}},
                                  {"fifa_ranking": 4})
        self.assertIn("H. Kane", p)
        self.assertIn("club form", p)


class TestKeyPlumbing(unittest.TestCase):
    def test_no_key_returns_none(self):
        saved = os.environ.pop("ANTHROPIC_API_KEY", None)
        saved_root = L.ROOT
        try:
            L.ROOT = "/nonexistent"
            self.assertIsNone(L.api_key())
        finally:
            L.ROOT = saved_root
            if saved is not None:
                os.environ["ANTHROPIC_API_KEY"] = saved

    def test_generate_skips_without_key(self):
        """Matchday safety: no key must mean a clean no-op, not a crash."""
        saved = os.environ.pop("ANTHROPIC_API_KEY", None)
        saved_root = L.ROOT
        try:
            L.ROOT = "/nonexistent"
            L.generate()   # must return without touching the network
        finally:
            L.ROOT = saved_root
            if saved is not None:
                os.environ["ANTHROPIC_API_KEY"] = saved


class TestSiteRendering(unittest.TestCase):
    def test_llm_section_renders(self):
        html = b.llm_section({"text": "First para.\n\nSecond para.",
                              "model": "claude-opus-4-8",
                              "generated": "2026-06-12 10:00 UTC"},
                             "The analyst's preview")
        self.assertIn("The analyst's preview", html)
        self.assertEqual(html.count("<p>First para.</p>"), 1)
        self.assertIn("claude-opus-4-8", html)
        self.assertIn("AI-written", html)

    def test_llm_section_absent(self):
        self.assertEqual(b.llm_section(None, "x"), "")
        self.assertEqual(b.llm_section({}, "x"), "")

    def test_llm_section_escapes(self):
        html = b.llm_section({"text": "a <script> b", "model": "m",
                              "generated": "t"}, "h")
        self.assertNotIn("<script>", html)


class TestSourcesFrozen(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(L.SOURCES), "sources not frozen yet")
    def test_sources_cover_all_teams(self):
        src = json.load(open(L.SOURCES))
        self.assertEqual(len(src["teams"]), 48)
        for name, t in src["teams"].items():
            self.assertTrue(t.get("wiki"), f"{name} missing wiki summary")
            self.assertIn("last_10", t)


if __name__ == "__main__":
    unittest.main()
