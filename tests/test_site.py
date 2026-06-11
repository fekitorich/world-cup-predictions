"""Site-builder unit tests + offline integration tests.

The integration test builds the real site into docs/ (idempotent) and then
audits it: template leaks, broken internal links, page counts, both languages.
"""
import os
import re
import sys
import unittest
from pathlib import Path

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.join(_ROOT, "pipeline"))

import wc26_build_site as b


class TestStandings(unittest.TestCase):
    def setUp(self):
        self._saved = [dict(m) for m in b.MATCHES]

    def tearDown(self):
        for m, s in zip(b.MATCHES, self._saved):
            m.clear()
            m.update(s)

    def test_standings_none_before_results(self):
        for m in b.MATCHES:
            m["score"] = None
        self.assertIsNone(b.group_standings("A"))

    def test_standings_order_and_points(self):
        for m in b.MATCHES:
            m["score"] = None
            if m["group"] == "A" and m["matchday"] == 1:
                m["score"] = "2-0" if m["home"] == "Mexico" else "1-1"
        s = b.group_standings("A")
        self.assertEqual(s[0][0], "Mexico")
        self.assertEqual(s[0][1]["pts"], 3)
        self.assertEqual(s[-1][1]["pts"], 0)
        self.assertEqual(sum(r["pts"] for _, r in s), 3 + 1 + 1 + 0)


class TestHelpers(unittest.TestCase):
    def test_actual_result(self):
        self.assertEqual(b.actual_result("2-1"), "home")
        self.assertEqual(b.actual_result("0-0"), "draw")
        self.assertEqual(b.actual_result("0-3"), "away")

    def test_is_live(self):
        self.assertFalse(b.is_live({"score": None, "status": "Not Started"}))
        self.assertFalse(b.is_live({"score": "1-0", "status": "Match Finished"}))
        self.assertTrue(b.is_live({"score": None, "status": "First Half"}))

    def test_slug_accents(self):
        self.assertEqual(b.slug("Kylian Mbappé"), "kylian-mbappe")
        self.assertEqual(b.slug("Curaçao"), "curacao")
        self.assertEqual(b.slug("Brahim Díaz"), "brahim-diaz")

    def test_ko_slug_suffix(self):
        m = {"home": "Mexico", "away": "Japan", "round": "Round of 32"}
        self.assertEqual(b.match_slug(m), "mexico-vs-japan-r32")


class TestCompleteness(unittest.TestCase):
    def test_every_team_has_flag(self):
        for t in b.TEAMS:
            self.assertTrue(b.flag(t), f"no flag for {t}")

    def test_every_team_has_id(self):
        for t in b.TEAMS:
            self.assertIn(t, b.TEAM_IDS)

    def test_every_team_has_squad_value(self):
        import json
        vals = json.load(open(Path(b.DATA) / "wc26_squad_values.json"))["values"]
        for t in b.TEAMS:
            self.assertIn(t, vals, f"no Transfermarkt value for {t}")

    def test_sims_cover_all_fixtures(self):
        for m in b.MATCHES:
            self.assertIn(str(m["match_id"]), b.SIMS)

    def test_sims_probabilities_valid(self):
        for mid, s in b.SIMS.items():
            ml = s["moneyline"]
            self.assertAlmostEqual(sum(ml.values()), 1.0, places=2, msg=mid)
            t = s["totals"]
            self.assertGreaterEqual(t["over_1.5"] + 1e-9, t["over_2.5"])
            self.assertGreaterEqual(t["over_2.5"] + 1e-9, t["over_3.5"])

    def test_sims_exact_scores_valid(self):
        for mid, s in b.SIMS.items():
            es = s["exact_scores"]
            self.assertEqual(len(es), 17, mid)   # 0-0..3-3 + other
            self.assertAlmostEqual(sum(es.values()), 1.0, places=2, msg=mid)
            top = s["top_scores"][0]   # mode can exceed 3 goals in blowouts
            if top["score"] in es:
                self.assertAlmostEqual(es[top["score"]], top["p"],
                                       places=4, msg=mid)


class TestBuiltSite(unittest.TestCase):
    """Integration: build and audit the artifact."""

    @classmethod
    def setUpClass(cls):
        b.build_all(snapshot=False)
        cls.docs = Path(b.OUT)
        cls.pages = list(cls.docs.glob("*.html")) \
            + list((cls.docs / "teams").glob("*.html")) \
            + list((cls.docs / "matches").glob("*.html")) \
            + list((cls.docs / "players").glob("*.html"))

    def test_report_page_graded_mode(self):
        """Inject synthetic results and verify every report section renders."""
        import copy
        saved = copy.deepcopy(b.PRED)
        try:
            for p in b.PRED["group_matches"][:6]:
                p["actual_score"] = "2-1"
                p["actual_result"] = "H"
                p["hit"] = p["pred_result"] == "H"
            b.PRED["accuracy"] = {
                "graded_group_matches": 6, "result_hits": 4,
                "result_pct": 0.667, "exact_score_hits": 1,
                "exact_score_pct": 0.167, "brier": 0.55,
                "market_priced_matches": 5,
                "compare": {"blend": {"brier": 0.55, "logloss": 0.9},
                            "model": {"brier": 0.56, "logloss": 0.92},
                            "market": {"brier": 0.54, "logloss": 0.89}},
                "stages": {}, "champion_correct": None}
            b.build_report()
            html = (Path(b.OUT) / "report.html").read_text()
            for needle in ("Who forecasts best", "Matchday by matchday",
                           "Sharpest calls", "Calibration so far"):
                self.assertIn(needle, html)
            self.assertNotIn("{", html.split("<main")[1].split("</main>")[0]
                             .replace("{ ", ""))
        finally:
            b.PRED.clear()
            b.PRED.update(saved)
            b.build_report()

    def test_page_counts(self):
        self.assertEqual(len(list((self.docs / "teams").glob("*.html"))), 48)
        self.assertEqual(len(list((self.docs / "matches").glob("*.html"))),
                         len(b.MATCHES) + len(b.KOS))
        self.assertGreaterEqual(
            len(list((self.docs / "players").glob("*.html"))), 30)
        for p in ("index", "matches", "futures", "awards", "bracket",
                  "report", "method", "method-fa", "archive"):
            self.assertTrue((self.docs / f"{p}.html").exists(), p)

    def test_no_template_leaks(self):
        leak = re.compile(r"\{(?:inline_svg|grid_inline|escape\(|m\[|pride|wrap_)")
        for p in self.pages:
            self.assertIsNone(leak.search(p.read_text()),
                              f"template leak in {p.name}")

    def test_internal_links_resolve(self):
        href = re.compile(r'href="([^"#]+?)(?:#[^"]*)?"')
        broken = []
        for p in self.pages:
            base = p.parent
            for link in href.findall(p.read_text()):
                if link.startswith(("http", "mailto", "data:")):
                    continue
                target = (base / link.split("?")[0]).resolve()
                if not target.exists():
                    broken.append(f"{p.relative_to(self.docs)} -> {link}")
        self.assertFalse(broken[:10], f"{len(broken)} broken links")

    def test_method_timeline_both_languages(self):
        for name, heading in (("method.html", "How the method evolved"),
                              ("method-fa.html", "سیر تکامل روش")):
            html = (self.docs / name).read_text()
            self.assertIn(heading, html, name)
            tl = html.split('<ol class="timeline">')[1].split("</ol>")[0]
            self.assertGreaterEqual(tl.count("<li>"), 8, name)

    def test_farsi_page_rtl_and_charts(self):
        fa = (self.docs / "method-fa.html").read_text()
        self.assertIn('dir="rtl"', fa)
        self.assertGreaterEqual(fa.count("<svg"), 4)

    def test_og_tags_everywhere(self):
        for p in self.pages[:20]:
            self.assertIn('property="og:title"', p.read_text(), p.name)

    def test_cname_emitted(self):
        """Pages custom domain: build must emit docs/CNAME every rebuild."""
        self.assertEqual((self.docs / "CNAME").read_text().strip(),
                         "wcformbook.com")

    def test_og_image_on_custom_domain(self):
        html = (self.docs / "index.html").read_text()
        self.assertIn('property="og:image" '
                      'content="https://wcformbook.com/', html)


if __name__ == "__main__":
    unittest.main()
