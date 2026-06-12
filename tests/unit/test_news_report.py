"""Unit: the local news-gate report page renders the log faithfully,
escapes everything, and never crashes on missing state."""
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, _ROOT)

from betting.news_report import render


LOG = {"runs": [
    {"at": "2026-06-12 17:34 UTC", "mode": "plan", "model": "claude-opus-4-8",
     "reports": [{"dossier_id": "101", "fixture": "Mexico v Canada",
                  "report": {"flags": [{"bet": "Mexico ML", "flag": "veto",
                                        "reasons": ["star out <script>"]}],
                             "key_absences": [{"team": "Mexico",
                                               "player": "R. Jiménez",
                                               "status": "confirmed"}],
                             "summary": "Striker ruled out."},
                  "advisories": [{"team": "Mexico", "player": "R. Jiménez",
                                  "goal_share": 0.4,
                                  "moneyline_before": {"home": 0.6},
                                  "moneyline_adjusted": {"home": 0.5}}]}],
     "applied": {"dropped": ["Mexico ML"], "scaled": [],
                 "analyst_failures": 0}},
    {"at": "2026-06-12 18:00 UTC", "mode": "holdings", "model": "m",
     "reports": [],
     "applied": {"flagged": [["review", "Australia (YES)", ["form dip"]]]}},
]}
PLAN = {"bets": [{"bet": "Canada win_group — YES", "stake_usdc": 1.93,
                  "model_p": 0.57, "market_p": 0.32, "category": "futures"}]}
LEDGER = {"placed": [{"stake_usdc": 10.0}]}


class TestRender(unittest.TestCase):
    def setUp(self):
        self.html = render(LOG, PLAN, LEDGER)

    def test_surviving_plan_and_tallies(self):
        self.assertIn("Canada win_group — YES", self.html)
        self.assertIn("1 kept", self.html)
        self.assertIn("1 removed", self.html)

    def test_flags_reasons_and_advisory(self):
        self.assertIn("VETO", self.html)
        self.assertIn("Striker ruled out.", self.html)
        self.assertIn("40% of Mexico goals", self.html)

    def test_holdings_flags(self):
        self.assertIn("Australia (YES)", self.html)
        self.assertIn("form dip", self.html)

    def test_everything_escaped(self):
        self.assertNotIn("<script>", self.html)

    def test_empty_state_never_crashes(self):
        page = render(None, None, None)
        self.assertIn("No plan-mode run logged yet", page)


if __name__ == "__main__":
    unittest.main()
