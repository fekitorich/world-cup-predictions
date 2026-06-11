"""Fetch reference profiles for the award-board candidates.

  python3 wc26_player_pages.py   ->  wc26_player_profiles.json

Candidates = everyone on the Golden Boot board, the Golden Ball market list
and the Golden Glove leans (~40 players). For each: bio (birth, height,
photo) and per-competition season stats (club + country) from API-Football.
Roughly 140 API calls; re-run occasionally during the tournament.
"""
import json
import os
import time
import unicodedata
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
KEY = os.environ.get("API_FOOTBALL_KEY") or \
    open(f"{ROOT}/.api_football_key").read().strip()
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
            return d["response"]
        except Exception as e:
            print("  http error:", e, flush=True)
            time.sleep(5)
    return []


def norm(s):
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def candidates():
    a = json.load(open(f"{DATA}/wc26_awards.json"))
    out = []
    for b in a["golden_boot"]:
        out.append((b["player"], b["team"]))
    for b in a["golden_ball"]:
        if b.get("team"):
            out.append((b["player"], b["team"]))
    for g in a["golden_glove"][:10]:
        out.append((g["player"], g["team"]))
    seen, uniq = set(), []
    for name, team in out:
        k = (norm(name).split()[-1], team)
        if k not in seen:
            seen.add(k)
            uniq.append((name, team))
    return uniq


def main():
    ids = {name: d["team_id"]
           for name, d in json.load(open(f"{DATA}/wc26_matches.json")).items()}
    squads = {}     # team -> [(id, api name)]
    profiles = {}
    cands = candidates()
    print(f"{len(cands)} candidates")
    for name, team in cands:
        if team not in squads:
            sq = api("players/squads", team=ids[team])
            squads[team] = [(p["id"], p["name"])
                            for p in (sq[0]["players"] if sq else [])]
            time.sleep(0.1)
        last = norm(name).split()[-1]
        hits = [(pid, nm) for pid, nm in squads[team]
                if norm(nm).split()[-1] == last or norm(nm) == norm(name)]
        if not hits:
            print(f"  ?? {name} not found in {team} squad")
            continue
        pid, api_name = hits[0]
        prof = {"team": team, "api_name": api_name, "seasons": {}}
        for season in SEASONS:
            recs = api("players", id=pid, season=season)
            time.sleep(0.1)
            if not recs:
                continue
            rec = recs[0]
            p = rec["player"]
            prof.setdefault("bio", {
                "name": p.get("name"),
                "fullname": f'{p.get("firstname", "")} {p.get("lastname", "")}'.strip(),
                "age": p.get("age"),
                "birth_date": (p.get("birth") or {}).get("date"),
                "birth_place": ", ".join(filter(None, [
                    (p.get("birth") or {}).get("place"),
                    (p.get("birth") or {}).get("country")])),
                "height": p.get("height"),
                "weight": p.get("weight"),
                "photo": p.get("photo"),
            })
            rows = []
            for s in rec["statistics"]:
                if not (s["games"]["appearences"] or 0):
                    continue
                rows.append({
                    "team": s["team"]["name"],
                    "competition": s["league"]["name"],
                    "apps": s["games"]["appearences"] or 0,
                    "minutes": s["games"]["minutes"] or 0,
                    "goals": s["goals"]["total"] or 0,
                    "assists": s["goals"]["assists"] or 0,
                    "rating": (round(float(s["games"]["rating"]), 2)
                               if s["games"]["rating"] else None),
                    "position": s["games"]["position"],
                })
            if rows:
                prof["seasons"][str(season)] = rows
        profiles[name] = prof
        ng = sum(r["goals"] for rows in prof["seasons"].values() for r in rows)
        print(f"  {name} ({team}): id={pid}, {len(prof['seasons'])} seasons, "
              f"{ng} goals all comps", flush=True)
    out = {"fetched_at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
           "profiles": profiles}
    json.dump(out, open(f"{DATA}/wc26_player_profiles.json", "w"),
              indent=2, ensure_ascii=False)
    from wc26_simulate import save_versioned
    save_versioned(f"{DATA}/wc26_player_profiles.json")
    print(f"wrote {len(profiles)} profiles")


if __name__ == "__main__":
    main()
