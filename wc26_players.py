"""Fetch WC2026 squads, player international scoring records, and
Polymarket award-market prices.

  python3 wc26_players.py   ->  wc26_players.json

- Squads + per-player NT goals/apps (seasons 2024-2026) from API-Football.
- Award prices (Golden Boot / Ball / Glove, top scoring nation) from the
  free Polymarket Gamma API.
"""
import json
import os
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.abspath(__file__))
KEY = os.environ.get("API_FOOTBALL_KEY") or \
    open(os.path.join(ROOT, ".api_football_key")).read().strip()
SEASONS = (2024, 2025, 2026)

def api(path, **q):
    url = f"https://v3.football.api-sports.io/{path}?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"x-apisports-key": KEY})
    for _ in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                d = json.load(r)
            if d.get("errors") and len(d["errors"]):
                print("  api error:", d["errors"], flush=True)
                time.sleep(5)
                continue
            return d
        except Exception as e:
            print("  http error:", e, flush=True)
            time.sleep(5)
    return None


def gamma(path, **q):
    url = f"https://gamma-api.polymarket.com{path}?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "wc26-research"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def fetch_team(name, team_id):
    sq = api("players/squads", team=team_id)
    players = {}
    for p in (sq["response"][0]["players"] if sq and sq["response"] else []):
        players[p["id"]] = {"name": p["name"], "position": p["position"],
                            "age": p["age"], "goals": 0, "apps": 0}
    for season in SEASONS:
        page = 1
        while True:
            d = api("players", team=team_id, season=season, page=page)
            if not d:
                break
            for rec in d["response"]:
                pid = rec["player"]["id"]
                g = sum(s["goals"]["total"] or 0 for s in rec["statistics"])
                a = sum(s["games"]["appearences"] or 0 for s in rec["statistics"])
                if pid in players:
                    players[pid]["goals"] += g
                    players[pid]["apps"] += a
                # players who left the squad still contributed to team totals
            if page >= d["paging"]["total"]:
                break
            page += 1
            time.sleep(0.1)
        time.sleep(0.1)
    return list(players.values())


def fetch_award_prices():
    out = {}
    slugs = {
        "golden_boot": "world-cup-golden-boot-winner",
        "golden_ball": "world-cup-golden-ball-winner-20260603194031758",
        "golden_glove": "world-cup-golden-glove-winner-20260603195306910",
        "top_scorer_nation": "world-cup-top-scorer-nation",
    }
    import re
    for key, slug in slugs.items():
        evs = gamma("/events", slug=slug)
        prices = {}
        for mk in (evs[0]["markets"] if evs else []):
            title = mk.get("groupItemTitle") or mk["question"]
            if re.fullmatch(r"Player [A-Z]{1,2}", title):
                continue   # unopened placeholder slot, not a real market
            try:
                prices[title] = float(json.loads(mk["outcomePrices"])[0])
            except (KeyError, ValueError, IndexError):
                pass
        out[key] = dict(sorted(prices.items(), key=lambda kv: -kv[1]))
        print(f"{key}: {len(prices)} outcomes, favourite: "
              f"{next(iter(out[key]), '?')}", flush=True)
        time.sleep(0.3)
    return out


def main():
    # resolve team ids from the fetch cache (already mapped during last-10 fetch)
    ids = {name: d["team_id"]
           for name, d in json.load(open(f"{ROOT}/wc26_matches.json")).items()}
    teams = {}
    for i, (name, tid) in enumerate(ids.items(), 1):
        teams[name] = fetch_team(name, tid)
        ng = sum(p["goals"] for p in teams[name])
        print(f"[{i}/48] {name}: {len(teams[name])} players, "
              f"{ng} intl goals 2024-26", flush=True)
    out = {
        "fetched_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "seasons": list(SEASONS),
        "squads": teams,
        "market": fetch_award_prices(),
    }
    json.dump(out, open(f"{ROOT}/wc26_players.json", "w"), indent=2,
              ensure_ascii=False)
    from wc26_simulate import save_versioned
    save_versioned(f"{ROOT}/wc26_players.json")
    print("wrote wc26_players.json")


if __name__ == "__main__":
    main()
