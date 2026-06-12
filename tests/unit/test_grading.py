"""Unit: the accuracy-grading math in wc26_update_results — the only code
allowed to write into the LOCKED predictions file, so every branch of it
is exercised here on synthetic fixtures."""
import math
import os
import sys
import unittest

_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

import wc26_update_results as U


def fx(mid, gh=None, ga=None, status="FT", rnd="Group Stage - 1",
       home="Alpha", away="Beta", hw=None, aw=None):
    return {"fixture": {"id": mid, "status": {"short": status}},
            "goals": {"home": gh, "away": ga},
            "league": {"round": rnd},
            "teams": {"home": {"name": home, "winner": hw},
                      "away": {"name": away, "winner": aw}}}


def pick(mid=1, pred="H", score="2-0", p=None, **extra):
    return {"match_id": mid, "pred_result": pred, "pred_score": score,
            "p": p or {"H": 0.5, "D": 0.3, "A": 0.2}, **extra}


class TestGradeGroupMatches(unittest.TestCase):
    def test_home_win_hit_and_exact(self):
        picks = [pick()]
        g = U.grade_group_matches(picks, {1: fx(1, 2, 0)})
        self.assertEqual((g["graded"], g["res_hit"], g["score_hit"]), (1, 1, 1))
        self.assertEqual(picks[0]["actual_result"], "H")
        self.assertTrue(picks[0]["hit"])

    def test_draw_and_away_mapping(self):
        picks = [pick(1, pred="D"), pick(2, pred="H")]
        g = U.grade_group_matches(picks, {1: fx(1, 1, 1), 2: fx(2, 0, 3)})
        self.assertEqual(picks[0]["actual_result"], "D")
        self.assertTrue(picks[0]["hit"])
        self.assertEqual(picks[1]["actual_result"], "A")
        self.assertFalse(picks[1]["hit"])
        self.assertEqual(g["res_hit"], 1)

    def test_unfinished_match_not_graded_and_stale_actual_cleared(self):
        picks = [pick(1, actual_score="9-9")]   # stale from an earlier run
        g = U.grade_group_matches(picks, {1: fx(1, status="NS")})
        self.assertEqual(g["graded"], 0)
        self.assertNotIn("actual_score", picks[0])

    def test_brier_and_logloss_blend(self):
        picks = [pick()]   # p = H .5 / D .3 / A .2, actual H
        g = U.grade_group_matches(picks, {1: fx(1, 1, 0)})
        self.assertAlmostEqual(g["briers"]["blend"],
                               0.5 ** 2 + 0.3 ** 2 + 0.2 ** 2, places=9)
        self.assertAlmostEqual(g["lls"]["blend"], -math.log(0.5), places=9)

    def test_market_probs_normalized_before_grading(self):
        """Polymarket books over-round; grading must renormalize first."""
        picks = [pick(p_market={"H": 0.6, "D": 0.3, "A": 0.3})]   # sums 1.2
        g = U.grade_group_matches(picks, {1: fx(1, 1, 0)})
        self.assertEqual(g["mkt_n"], 1)
        self.assertAlmostEqual(g["lls"]["market"], -math.log(0.5), places=9)

    def test_unpriced_match_skips_market_source(self):
        g = U.grade_group_matches([pick()], {1: fx(1, 1, 0)})
        self.assertEqual(g["mkt_n"], 0)
        self.assertEqual(g["briers"]["market"], 0.0)


class TestKnockoutActuals(unittest.TestCase):
    def test_r32_winner_reaches_r16(self):
        stages, champ = U.knockout_actuals(
            [fx(73, 1, 0, rnd="Round of 32", hw=True)])
        self.assertEqual(stages["r16"], {"Alpha"})
        self.assertIsNone(champ)

    def test_stage_ladder(self):
        stages, _ = U.knockout_actuals(
            [fx(89, 2, 1, rnd="Round of 16", hw=True),
             fx(97, 0, 2, rnd="Quarter-finals", aw=True, away="Gamma"),
             fx(101, 1, 0, rnd="Semi-finals", hw=True)])
        self.assertEqual(stages["qf"], {"Alpha"})
        self.assertEqual(stages["sf"], {"Gamma"})
        self.assertEqual(stages["final"], {"Alpha"})

    def test_semi_final_is_not_the_final(self):
        """'Semi-finals' contains the word 'final' — must not crown anyone."""
        _, champ = U.knockout_actuals(
            [fx(101, 1, 0, rnd="Semi-finals", hw=True)])
        self.assertIsNone(champ)

    def test_third_place_playoff_is_not_the_final(self):
        _, champ = U.knockout_actuals(
            [fx(103, 2, 0, rnd="3rd Place Final", hw=True)])
        self.assertIsNone(champ)

    def test_final_crowns_champion_with_alias_normalized(self):
        _, champ = U.knockout_actuals(
            [fx(104, 1, 0, rnd="Final", home="Türkiye", hw=True)])
        self.assertEqual(champ, "Turkey")

    def test_no_winner_flag_no_claim(self):
        stages, champ = U.knockout_actuals([fx(104, None, None, rnd="Final",
                                               status="FT")])
        self.assertEqual(stages["final"], set())
        self.assertIsNone(champ)


if __name__ == "__main__":
    unittest.main()
