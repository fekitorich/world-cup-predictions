"""Fetch Polymarket moneyline prices for all 72 WC2026 group fixtures.

Free Gamma API, no key. Event slug pattern: fifwc-{home}-{away}-{YYYY-MM-DD}
with lowercase FIFA trigrams. Falls back to public-search on slug miss.
Exact-score books live in sibling events at {slug}-exact-score; snapshotted
alongside the moneyline when listed.

Writes wc26_market_prices.json keyed by our match_id.
"""
import json
import os
import re
import time
import urllib.request
import urllib.parse

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
BASE = "https://gamma-api.polymarket.com"

FIFA_CODE = {
    "United States": "usa", "Canada": "can", "Mexico": "mex", "Panama": "pan",
    "Haiti": "hai", "Curaçao": "cuw", "Argentina": "arg", "Brazil": "bra",
    "Colombia": "col", "Uruguay": "uru", "Ecuador": "ecu", "Paraguay": "par",
    "Germany": "ger", "England": "eng", "France": "fra", "Spain": "esp",
    "Portugal": "por", "Netherlands": "ned", "Italy": "ita", "Belgium": "bel",
    "Austria": "aut", "Switzerland": "che", "Turkey": "tur", "Norway": "nor",
    "Sweden": "swe", "Czech Republic": "cze", "Bosnia and Herzegovina": "bih",
    "Croatia": "cro", "Scotland": "sco", "Morocco": "mar", "Senegal": "sen",
    "Egypt": "egy", "Ivory Coast": "civ", "South Africa": "rsa",
    "DR Congo": "cod", "Tunisia": "tun", "Algeria": "alg", "Ghana": "gha",
    "Cape Verde": "cvi", "Japan": "jpn", "South Korea": "kr", "Iran": "irn",
    "Australia": "aus", "Saudi Arabia": "ksa", "Uzbekistan": "uzb",
    "Jordan": "jor", "Qatar": "qat", "Iraq": "irq", "New Zealand": "nzl",
}


def get(path, **q):
    url = f"{BASE}{path}?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "wc26-research"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


# Polymarket question-text spellings that differ from ours
ALIASES = {
    "Turkey": ("türkiye", "turkiye", "turkey"),
    "South Korea": ("south korea", "korea republic"),
    "Ivory Coast": ("côte d'ivoire", "cote d'ivoire", "ivory coast"),
    "Czech Republic": ("czechia", "czech republic"),
    "Iran": ("ir iran", "iran"),
    "United States": ("united states", "usa"),
    "Bosnia and Herzegovina": ("bosnia-herzegovina", "bosnia and herzegovina"),
    "Curaçao": ("curaçao", "curacao"),
    "Cape Verde": ("cabo verde", "cape verde"),
    "DR Congo": ("dr congo", "congo dr"),
}


def names_for(team):
    return ALIASES.get(team, (team.lower(),))


SCORE_RE = re.compile(r"(\d+)\s*-\s*(\d+)")


def parse_score_question(q, home, away):
    """'Exact Score: Mexico 2 - 1 South Africa?' -> '2-1' (home goals first,
    whichever side Polymarket names first); 'Any Other Score?' -> 'other'."""
    ql = q.lower()
    if "exact score" not in ql:
        return None
    if "any other" in ql:
        return "other"
    m = SCORE_RE.search(ql)
    if not m:
        return None
    left = ql[:m.start()]
    if any(n in left for n in names_for(home)):
        return f"{m.group(1)}-{m.group(2)}"
    if any(n in left for n in names_for(away)):
        return f"{m.group(2)}-{m.group(1)}"
    return None


OU_RE = re.compile(r":\s*O/U (\d+\.5)\??$")        # full-match totals only:
SPREAD_RE = re.compile(r"^Spread: (.+?) \((-\d+\.5)\)\??$")   # team/half lines
                                                   # have words between : and O/U


def classify_more_market(q, home, away):
    """'United States vs. Paraguay: O/U 2.5' -> ('totals', 'over_2.5');
    '...: Both Teams to Score' -> ('btts', None);
    'Spread: United States (-1.5)' -> ('spread', 'home_-1.5');
    team totals and half markets -> None (no model for them)."""
    m = OU_RE.search(q)
    if m:
        return "totals", f"over_{m.group(1)}"
    if q.rstrip("?").endswith("Both Teams to Score"):
        return "btts", None
    m = SPREAD_RE.match(q)
    if m:
        name = m.group(1).lower()
        side = ("home" if any(n in name for n in names_for(home)) else
                "away" if any(n in name for n in names_for(away)) else None)
        if side:
            return "spread", f"{side}_{m.group(2)}"
    return None


def parse_more_markets(ev, home, away):
    """Full-match totals, BTTS and spreads from the -more-markets event."""
    totals, spread, btts = {}, {}, None
    for mk in ev.get("markets", []):
        cls = classify_more_market(mk.get("question", ""), home, away)
        if not cls:
            continue
        try:
            yes = float(json.loads(mk["outcomePrices"])[0])
            first = json.loads(mk.get("outcomes") or '["Yes"]')[0]
        except (KeyError, ValueError, IndexError):
            continue
        cat, key = cls
        if cat == "totals" and first == "Over":
            totals[key] = yes
        elif cat == "btts" and first == "Yes":
            btts = yes
        elif cat == "spread":
            spread[key] = yes
    out = {}
    if totals:
        out["totals"] = totals
    if btts is not None:
        out["btts"] = btts
    if spread:
        out["spread"] = spread
    return out


def fetch_more_markets(base_slug, home, away):
    """Totals/BTTS/spread prices from the {slug}-more-markets sibling."""
    slug = f"{base_slug}-more-markets"
    try:
        evs = get("/events", slug=slug)
    except Exception as e:
        print(f"  more-markets fetch failed {slug}: {e}", flush=True)
        return None, None
    if not evs:
        return None, None
    parsed = parse_more_markets(evs[0], home, away)
    return (slug, parsed) if parsed else (None, None)


def fetch_exact_scores(base_slug, home, away):
    """Yes-price per scoreline cell from the {slug}-exact-score sibling."""
    slug = f"{base_slug}-exact-score"
    try:
        evs = get("/events", slug=slug)
    except Exception as e:
        print(f"  exact-score fetch failed {slug}: {e}", flush=True)
        return None, None
    if not evs:
        return None, None
    cells = {}
    for mk in evs[0].get("markets", []):
        cell = parse_score_question(mk.get("question", ""), home, away)
        if not cell:
            continue
        try:
            cells[cell] = float(json.loads(mk["outcomePrices"])[0])
        except (KeyError, ValueError, IndexError):
            continue
    if len(cells) < 5:   # half-listed book: not a usable price surface
        return None, None
    return slug, cells


def parse_event(ev, home, away):
    """Extract home/draw/away Yes-prices from an event's binary markets."""
    out = {}
    for mk in ev.get("markets", []):
        q = mk["question"].lower()
        try:
            prices = json.loads(mk["outcomePrices"])
            yes = float(prices[0])
        except (KeyError, ValueError, IndexError):
            continue
        if "draw" in q:
            out["draw"] = yes
        elif any(f"will {n} win" in q for n in names_for(home)):
            out["home"] = yes
        elif any(f"will {n} win" in q for n in names_for(away)):
            out["away"] = yes
    if {"home", "draw", "away"} <= out.keys():
        return {
            "moneyline": out,
            "slug": ev["slug"],
            "volume": round(float(ev.get("volume") or 0)),
            "liquidity": round(float(ev.get("liquidity") or 0)),
        }
    return None


def fetch_fixture(m):
    from datetime import date, timedelta
    home, away = m["home"], m["away"]
    day = date.fromisoformat(m["date_utc"][:10])
    # Polymarket slugs use the US-local match date, often UTC-1 day
    days = [str(day - timedelta(days=1)), str(day), str(day + timedelta(days=1))]
    for d in days:
        slug = f"fifwc-{FIFA_CODE[home]}-{FIFA_CODE[away]}-{d}"
        try:
            evs = get("/events", slug=slug)
            if evs:
                r = parse_event(evs[0], home, away)
                if r:
                    return r
        except Exception as e:
            print(f"  slug fetch failed {slug}: {e}", flush=True)
    # fallback: search by title
    try:
        res = get("/public-search", q=f"{home} vs {away}", limit_per_type=5)
        for ev in res.get("events", []):
            if ev.get("slug", "").startswith("fifwc-") and \
                    any(d in ev["slug"] for d in days):
                r = parse_event(ev, home, away)
                if r:
                    return r
    except Exception as e:
        print(f"  search failed {home} v {away}: {e}", flush=True)
    return None


def main():
    fixtures = json.load(
        open(f"{DATA}/fifa_world_cup_2026_group_matches.json"))["matches"]
    try:
        fixtures += json.load(
            open(f"{DATA}/wc26_knockout_matches.json"))["matches"]
    except FileNotFoundError:
        pass
    out, misses = {}, []
    n_es = 0
    for m in fixtures:
        r = fetch_fixture(m)
        if r:
            es_slug, cells = fetch_exact_scores(r["slug"], m["home"], m["away"])
            if cells:
                r["exact_score_slug"] = es_slug
                r["exact_score"] = cells
                n_es += 1
            mm_slug, mm = fetch_more_markets(r["slug"], m["home"], m["away"])
            if mm:
                r["more_markets_slug"] = mm_slug
                r.update(mm)   # totals / btts / spread
            out[str(m["match_id"])] = r
        else:
            misses.append(f"{m['home']} v {m['away']} {m['date_utc'][:10]}")
        time.sleep(0.15)
    json.dump({"fetched_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
               "source": "Polymarket Gamma API", "prices": out},
              open(f"{DATA}/wc26_market_prices.json", "w"), indent=2)
    from wc26_simulate import save_versioned
    save_versioned(f"{DATA}/wc26_market_prices.json")
    n_mm = sum(1 for r in out.values() if "more_markets_slug" in r)
    print(f"got prices for {len(out)}/{len(fixtures)} fixtures "
          f"({n_es} with exact-score books, {n_mm} with totals/BTTS/spread)")
    if misses:
        print("missing:", "; ".join(misses))


if __name__ == "__main__":
    main()
