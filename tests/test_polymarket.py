"""Offline tests for the Polymarket fetch/parse layer (no network)."""
import json
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

from wc26_polymarket import (FIFA_CODE, names_for, parse_event,
                             classify_more_market, parse_more_markets,
                             parse_half_event, parse_first_to_score,
                             parse_corners)


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

    def test_codes_are_lowercase_short(self):
        for team, code in FIFA_CODE.items():   # kr (South Korea) is 2 chars
            self.assertRegex(code, r"^[a-z]{2,3}$", team)

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


class TestMoreMarkets(unittest.TestCase):
    H, A = "United States", "Paraguay"

    def test_classify_totals(self):
        self.assertEqual(
            classify_more_market("United States vs. Paraguay: O/U 2.5",
                                 self.H, self.A), ("totals", "over_2.5"))

    def test_classify_team_totals(self):
        self.assertEqual(
            classify_more_market("United States vs. Paraguay: United States O/U 2.5",
                                 self.H, self.A), ("team_totals", "home_over_2.5"))
        self.assertEqual(
            classify_more_market("United States vs. Paraguay: Paraguay O/U 0.5",
                                 self.H, self.A), ("team_totals", "away_over_0.5"))

    def test_classify_skips_half_markets(self):
        for q in ("United States vs. Paraguay: 1st Half O/U 0.5",
                  "United States vs. Paraguay: Paraguay 2nd Half O/U 1.5",
                  "United States vs. Paraguay: United States 1st Half O/U 1.5"):
            self.assertIsNone(classify_more_market(q, self.H, self.A), q)

    def test_classify_btts_full_match_only(self):
        self.assertEqual(
            classify_more_market("United States vs. Paraguay: Both Teams to Score",
                                 self.H, self.A), ("btts", None))
        self.assertIsNone(classify_more_market(
            "United States vs. Paraguay: Both Teams to Score in First Half",
            self.H, self.A))

    def test_classify_spread_sides(self):
        self.assertEqual(
            classify_more_market("Spread: United States (-1.5)", self.H, self.A),
            ("spread", "home_-1.5"))
        self.assertEqual(
            classify_more_market("Spread: Paraguay (-2.5)", self.H, self.A),
            ("spread", "away_-2.5"))

    def test_parse_more_markets(self):
        def mm(q, yes, outcomes):
            return {"question": q,
                    "outcomePrices": json.dumps([str(yes), str(1 - yes)]),
                    "outcomes": json.dumps(outcomes)}
        ev = {"markets": [
            mm("United States vs. Paraguay: O/U 2.5", 0.415, ["Over", "Under"]),
            mm("United States vs. Paraguay: O/U 3.5", 0.215, ["Over", "Under"]),
            mm("United States vs. Paraguay: Both Teams to Score", 0.465,
               ["Yes", "No"]),
            mm("Spread: United States (-1.5)", 0.235,
               ["United States", "Paraguay"]),
            mm("United States vs. Paraguay: 1st Half O/U 0.5", 0.650,
               ["Over", "Under"]),   # half market: must be ignored
        ]}
        out = parse_more_markets(ev, self.H, self.A)
        self.assertEqual(out["totals"],
                         {"over_2.5": 0.415, "over_3.5": 0.215})
        self.assertEqual(out["btts"], 0.465)
        self.assertEqual(out["spread"], {"home_-1.5": 0.235})


class TestSiblingParsers(unittest.TestCase):
    H, A = "United States", "Paraguay"

    def ev(self, *qs):
        return {"markets": [
            {"question": q, "outcomePrices": json.dumps([str(p), str(1 - p)]),
             "outcomes": json.dumps(o)} for q, p, o in qs]}

    def test_parse_halftime(self):
        ev = self.ev(
            ("United States leading at halftime?", 0.345, ["Yes", "No"]),
            ("United States vs. Paraguay: Draw at halftime?", 0.465, ["Yes", "No"]),
            ("Paraguay leading at halftime?", 0.195, ["Yes", "No"]))
        self.assertEqual(parse_half_event(ev, self.H, self.A),
                         {"home": 0.345, "draw": 0.465, "away": 0.195})

    def test_parse_second_half_phrasing(self):
        ev = self.ev(
            ("United States to win the second half?", 0.40, ["Yes", "No"]),
            ("Paraguay to win the second half?", 0.38, ["Yes", "No"]),
            ("United States vs. Paraguay: Second half draw?", 0.51, ["Yes", "No"]))
        self.assertEqual(parse_half_event(ev, self.H, self.A),
                         {"home": 0.40, "away": 0.38, "draw": 0.51})

    def test_parse_incomplete_half_book_rejected(self):
        ev = self.ev(("United States leading at halftime?", 0.345, ["Yes", "No"]))
        self.assertIsNone(parse_half_event(ev, self.H, self.A))

    def test_parse_first_to_score(self):
        ev = self.ev(
            ("Paraguay to score first vs. United States?", 0.345, ["Yes", "No"]),
            ("United States to score first vs. Paraguay?", 0.565, ["Yes", "No"]),
            ("United States vs. Paraguay: Neither team to score first?",
             0.105, ["Yes", "No"]))
        self.assertEqual(parse_first_to_score(ev, self.H, self.A),
                         {"away": 0.345, "home": 0.565, "neither": 0.105})

    def test_parse_corners_full_match_only(self):
        ev = self.ev(
            ("United States vs. Paraguay: O/U 9.5 Total Corners", 0.43, ["Over", "Under"]),
            ("United States vs. Paraguay: 2nd Half O/U 4.5 Total Corners", 0.5, ["Over", "Under"]),
            ("United States vs. Paraguay: United States O/U 4.5 Corners", 0.5, ["Over", "Under"]))
        self.assertEqual(parse_corners(ev, self.H, self.A), {"over_9.5": 0.43})


if __name__ == "__main__":
    unittest.main()
