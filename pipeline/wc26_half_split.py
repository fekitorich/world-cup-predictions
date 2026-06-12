"""Fit half_split — the share of goals scored before halftime.

Pulls finished fixtures with halftime scores from API-Football for recent
international tournaments, reports the per-tournament split (stability
check), and writes the pooled value into wc26_params.json.

  python3 pipeline/wc26_half_split.py
"""
import json
import os
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
KEY = os.environ.get("API_FOOTBALL_KEY") or \
    open(os.path.join(ROOT, ".api_football_key")).read().strip()

# league id, season, label
SOURCES = [
    (1, 2022, "World Cup 2022"),
    (4, 2024, "Euro 2024"),
    (9, 2024, "Copa America 2024"),
    (6, 2023, "Africa Cup of Nations 2023"),
    (7, 2023, "Asian Cup 2023"),
    (10, 2025, "Friendlies 2025"),
]


def fetch(league, season):
    url = (f"https://v3.football.api-sports.io/fixtures?"
           f"league={league}&season={season}")
    req = urllib.request.Request(url, headers={"x-apisports-key": KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["response"]


def main():
    pooled_ht = pooled_ft = 0
    for league, season, label in SOURCES:
        ht = ft = n = 0
        for f in fetch(league, season):
            if f["fixture"]["status"]["short"] not in ("FT", "AET", "PEN"):
                continue
            h = f["score"]["halftime"]
            full = f["score"]["fulltime"]
            if None in (h["home"], h["away"], full["home"], full["away"]):
                continue
            ht += h["home"] + h["away"]
            ft += full["home"] + full["away"]   # 90-minute score
            n += 1
        if ft:
            print(f"{label}: {n} matches, {ht}/{ft} goals before HT "
                  f"-> split {ht / ft:.3f}")
            pooled_ht += ht
            pooled_ft += ft
    split = round(pooled_ht / pooled_ft, 3)
    print(f"\nPOOLED: {pooled_ht}/{pooled_ft} -> half_split = {split}")
    doc = json.load(open(f"{DATA}/wc26_params.json"))
    doc["params"]["half_split"] = split
    doc["half_split_note"] = (f"share of goals before HT, fit on "
                              f"{pooled_ft} goals across {len(SOURCES)} "
                              "international tournaments")
    json.dump(doc, open(f"{DATA}/wc26_params.json", "w"), indent=2)
    print("wrote half_split to wc26_params.json")


if __name__ == "__main__":
    main()
