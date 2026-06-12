"""Smoke: the repo as checked out is runnable. Every script parses,
every canonical data file is valid JSON, the entry points exist.
Fast and dumb on purpose — this layer catches 'someone broke the tree',
not logic bugs."""
import glob
import json
import os
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class TestScriptsParse(unittest.TestCase):
    def test_every_python_script_compiles(self):
        files = (glob.glob(os.path.join(ROOT, "pipeline", "*.py"))
                 + glob.glob(os.path.join(ROOT, "betting", "*.py")))
        self.assertGreaterEqual(len(files), 15)
        for f in files:
            with self.subTest(script=os.path.basename(f)):
                compile(open(f).read(), f, "exec")   # syntax only, no exec


class TestDataFilesParse(unittest.TestCase):
    def test_every_canonical_json_parses(self):
        files = glob.glob(os.path.join(ROOT, "data", "*.json"))
        self.assertGreaterEqual(len(files), 10)
        for f in files:
            with self.subTest(file=os.path.basename(f)):
                json.load(open(f))


class TestEntryPoints(unittest.TestCase):
    def test_matchday_script_runs_the_gate(self):
        sh = open(os.path.join(ROOT, "wc26_matchday.sh")).read()
        self.assertIn("unittest discover", sh)

    def test_matchday_never_bets_or_generates_llm(self):
        """Money and API spend are user-triggered only — automation must
        never touch betting/ executors or wc26_llm.py generate."""
        sh = open(os.path.join(ROOT, "wc26_matchday.sh")).read()
        for forbidden in ("place_bets", "find_bets", "betting/run.py",
                          "wc26_llm.py generate"):
            self.assertNotIn(forbidden, sh)

    def test_betting_entry_points_exist(self):
        for f in ("run.py", "find_bets.py", "place_bets.py", "paper.py"):
            self.assertTrue(os.path.exists(os.path.join(ROOT, "betting", f)))

    def test_personal_files_gitignored(self):
        gi = open(os.path.join(ROOT, ".gitignore")).read()
        for pattern in (".env", "betting/config.local.json",
                        "betting/state/", ".api_football_key",
                        ".anthropic_key"):
            self.assertIn(pattern, gi)


if __name__ == "__main__":
    unittest.main()
