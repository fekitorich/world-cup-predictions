"""Repo-layout invariants: scripts compile, paths resolve, automation
references real files. Guards the pipeline/ + data/ structure so a future
reshuffle cannot silently break the matchday automation."""
import json
import os
import py_compile
import re
import sys
import unittest
from glob import glob

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

import wc26_simulate as sim

DATA_FILES = [
    "fifa_world_cup_2026.json", "fifa_world_cup_2026_group_matches.json",
    "international_results.csv", "wc26_awards.json", "wc26_data_patches.json",
    "wc26_espn_ids.json", "wc26_knockout_matches.json",
    "wc26_market_prices.json", "wc26_matches.json", "wc26_params.json",
    "wc26_player_profiles.json", "wc26_players.json", "wc26_predictions.json",
    "wc26_scorers.json", "wc26_simulations.json", "wc26_squad_values.json",
    "wc26_team_goals.npz", "wc26_tournament.json",
]


class TestLayout(unittest.TestCase):
    def test_root_and_data_resolve(self):
        self.assertEqual(os.path.realpath(sim.ROOT), os.path.realpath(_ROOT))
        self.assertTrue(os.path.isdir(sim.DATA))
        self.assertEqual(os.path.basename(sim.DATA), "data")

    def test_all_data_files_present(self):
        for f in DATA_FILES:
            self.assertTrue(os.path.exists(os.path.join(_ROOT, "data", f)),
                            f"data/{f} missing")

    def test_no_data_files_left_at_root(self):
        strays = [f for f in os.listdir(_ROOT)
                  if f.endswith((".json", ".csv", ".npz"))]
        self.assertEqual(strays, [], f"data files at repo root: {strays}")

    def test_every_script_compiles(self):
        for path in glob(os.path.join(_ROOT, "pipeline", "*.py")) + \
                glob(os.path.join(_ROOT, "betting", "*.py")):
            try:
                py_compile.compile(path, doraise=True)
            except py_compile.PyCompileError as e:
                self.fail(f"{path}: {e}")

    def test_matchday_script_calls_real_files(self):
        """Every script invoked by the launchd matchday job must exist."""
        src = open(os.path.join(_ROOT, "wc26_matchday.sh")).read()
        called = re.findall(r"(pipeline/\S+\.py)", src)
        self.assertGreaterEqual(len(called), 7)
        for rel in called:
            self.assertTrue(os.path.exists(os.path.join(_ROOT, rel)),
                            f"matchday.sh calls missing {rel}")

    def test_no_stale_root_references(self):
        """No script may open a data file at the repo root anymore."""
        pat = re.compile(r"""ROOT[}/].{0,3}(?:wc26_\w+\.(?:json|npz|csv)
                             |fifa_world_cup|international_results)""",
                         re.VERBOSE)
        for path in glob(os.path.join(_ROOT, "pipeline", "*.py")) + \
                glob(os.path.join(_ROOT, "betting", "*.py")) + \
                [os.path.join(_ROOT, "wc26_matchday.sh")]:
            for i, line in enumerate(open(path), 1):
                self.assertIsNone(pat.search(line),
                                  f"{path}:{i} stale ROOT data ref: {line!r}")

    def test_save_versioned_archives_to_runs(self):
        import tempfile
        with tempfile.TemporaryDirectory() as td:
            src = os.path.join(td, "wc26_probe.json")
            json.dump({"probe": True}, open(src, "w"))
            dst = sim.save_versioned(src)
            try:
                self.assertTrue(os.path.exists(dst))
                self.assertEqual(os.path.basename(os.path.dirname(dst)), "runs")
                self.assertIn("probe", os.path.basename(dst))
            finally:
                os.remove(dst)

    def test_locked_predictions_untouched_shape(self):
        """The locked bracket file must keep its grading-critical keys."""
        pred = json.load(open(os.path.join(_ROOT, "data",
                                           "wc26_predictions.json")))
        for key in ("locked_at", "champion", "group_matches", "knockout",
                    "actuals", "accuracy"):
            self.assertIn(key, pred)
        self.assertEqual(len(pred["group_matches"]), 72)


if __name__ == "__main__":
    unittest.main()
