"""Offline tests for the Polymarket fetch/parse layer (no network)."""
import json
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

from wc26_polymarket import FIFA_CODE, names_for, parse_event


def mk(question, yes):
    return {"question": question, "outcomePrices": json.dumps([str(yes), str(1 - yes)])}


def event(*markets):
    return {"slug": "fifwc-test", "volume": "1000", "liquidity": "500",
            "markets": list(markets)}


class TestFifaCodes(unittest.TestCase):
    def test_all_48_teams_have_codes(self):
        teams = json.load(open(os.path.join(_ROOT, "data",
                                            "fifa_world_cup_2026.json")))["teams"]
        for t in teams:
            self.assertIn(t["country"], FIFA_CODE, t["country"])
        self.assertGreaterEqual(len(FIFA_CODE), 48)   # 49: Italy lingers

    def test_codes_are_lowercase_trigrams(self):
        for team, code in FIFA_CODE.items():
            self.assertRegex(code, r"^[a-z]{3}$", team)

    def test_names_for_lowercase(self):
        for team in FIFA_CODE:
            for n in names_for(team):
                self.assertEqual(n, n.lower(), team)


class TestParseEvent(unittest.TestCase):
    def test_complete_moneyline(self):
        ev = event(
                   mk("Will Mexico win on 2026-06-11?", 0.86),
                   mk("Will Mexico vs. South Africa end in a draw?", 0.11),
                   mk("Will South Africa win on 2026-06-11?", 0.03))
        r = parse_event(ev, "Mexico", "South Africa")
        self.assertEqual(r["moneyline"],
                         {"home": 0.86, "draw": 0.11, "away": 0.03})
        self.assertEqual(r["volume"], 1000)

    def test_alias_resolution(self):
        ev = event(
                   mk("Will Türkiye win on 2026-06-22?", 0.40),
                   mk("Will Türkiye vs. USA end in a draw?", 0.27),
                   mk("Will USA win on 2026-06-22?", 0.33))
        r = parse_event(ev, "Turkey", "United States")
        self.assertEqual(r["moneyline"]["home"], 0.40)
        self.assertEqual(r["moneyline"]["away"], 0.33)

    def test_incomplete_event_rejected(self):
        ev = event(
                   mk("Will Mexico win on 2026-06-11?", 0.86))
        self.assertIsNone(parse_event(ev, "Mexico", "South Africa"))

    def test_malformed_prices_skipped(self):
        ev = event(
                   {"question": "Will Mexico win?", "outcomePrices": "junk"},
                   mk("Will Mexico vs. South Africa end in a draw?", 0.11),
                   mk("Will South Africa win on 2026-06-11?", 0.03))
        self.assertIsNone(parse_event(ev, "Mexico", "South Africa"))


if __name__ == "__main__":
    unittest.main()
