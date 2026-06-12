"""Total-corners model: negative binomial, validated before it prices.

  python3 pipeline/wc26_corners.py backfill  # fetch corner counts (~250 calls,
                                             # cached in data/wc26_corners_history.json)
  python3 pipeline/wc26_corners.py fit       # fit + leave-one-tournament-out
                                             # validation -> data/wc26_corners_model.json
  python3 pipeline/wc26_corners.py predict   # per-fixture O/U -> data/wc26_corners.json

Model: total corners ~ NegBin(mu, k), log(mu) = a + b * (total model xG).
The b=0 (intercept-only) variant is the baseline; b ships only if it wins
out of sample. Corners books are thin — this is a fair-value anchor, not
an edge machine.
"""
import json
import math
import os
import sys
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
KEY = os.environ.get("API_FOOTBALL_KEY") or \
    open(os.path.join(ROOT, ".api_football_key")).read().strip()
HIST = f"{DATA}/wc26_corners_history.json"
MODEL = f"{DATA}/wc26_corners_model.json"

# league id, season, fit cutoff (ratings as of just before the tournament)
SOURCES = [
    (1, 2022, "2022-11-15", "World Cup 2022"),
    (6, 2023, "2024-01-10", "AFCON 2023"),       # played Jan 2024
    (7, 2023, "2024-01-10", "Asian Cup 2023"),   # played Jan 2024
    (4, 2024, "2024-06-10", "Euro 2024"),
    (9, 2024, "2024-06-15", "Copa America 2024"),
]


def api(path):
    url = f"https://v3.football.api-sports.io/{path}"
    req = urllib.request.Request(url, headers={"x-apisports-key": KEY})
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)["response"]


def backfill():
    try:
        hist = json.load(open(HIST))
    except FileNotFoundError:
        hist = {}
    for league, season, _, label in SOURCES:
        fixtures = api(f"fixtures?league={league}&season={season}")
        n_new = 0
        for f in fixtures:
            fid = str(f["fixture"]["id"])
            if fid in hist or f["fixture"]["status"]["short"] not in \
                    ("FT", "AET", "PEN"):
                continue
            stats = api(f"fixtures/statistics?fixture={fid}")
            corners = {}
            for side in stats:
                for s in side["statistics"]:
                    if s["type"] == "Corner Kicks":
                        corners[side["team"]["name"]] = s["value"] or 0
            if len(corners) != 2:
                continue
            hist[fid] = {
                "league": label,
                "home": f["teams"]["home"]["name"],
                "away": f["teams"]["away"]["name"],
                "corners": sum(corners.values()),
            }
            n_new += 1
            time.sleep(0.15)
        print(f"{label}: +{n_new} fixtures", flush=True)
        json.dump(hist, open(HIST, "w"), indent=1)
    print(f"history: {len(hist)} fixtures total")


def nb_logpmf(y, mu, k):
    return (math.lgamma(y + k) - math.lgamma(k) - math.lgamma(y + 1)
            + k * math.log(k / (k + mu)) + y * math.log(mu / (k + mu)))


def nb_cdf_over(line, mu, k):
    """P(total corners > line) for a half-integer line."""
    return 1 - sum(math.exp(nb_logpmf(y, mu, k)) for y in range(int(line) + 1))


def match_xg(rows):
    """Total model xG per historical fixture, ratings fit at each
    tournament's cutoff (no look-ahead)."""
    from wc26_simulate import params, load_matches, fit, lambdas
    p = params()
    out = []
    for league, season, cutoff, label in SOURCES:
        model = fit(load_matches(cutoff, p["half_life"], p["friendly_w"],
                                 p["margin_cap"]), p["shrink"], iters=60)
        # name alignment: API-Football vs martj42 spellings
        alias = {"USA": "United States", "South Korea": "South Korea",
                 "Korea Republic": "South Korea", "Czechia": "Czech Republic",
                 "Türkiye": "Turkey", "Côte d'Ivoire": "Ivory Coast",
                 "Cabo Verde": "Cape Verde", "Congo DR": "DR Congo"}
        for r in rows:
            if r["league"] != label:
                continue
            h = alias.get(r["home"], r["home"])
            a = alias.get(r["away"], r["away"])
            if h not in model["att"] or a not in model["att"]:
                continue
            l1, l2 = lambdas(model, h, a, False)
            out.append({"league": label, "xg": l1 + l2, "y": r["corners"]})
        print(f"{label}: ratings fit, "
              f"{sum(1 for o in out if o['league'] == label)} matches matched",
              flush=True)
    return out


def fit_nb(data, b_fixed=None):
    """ML fit of (a, b, k) by coordinate grid descent (stdlib)."""
    mean_y = sum(d["y"] for d in data) / len(data)
    mean_x = sum(d["xg"] for d in data) / len(data)
    a, b, k = math.log(mean_y), 0.0 if b_fixed is None else b_fixed, 10.0

    def ll(a, b, k):
        return sum(nb_logpmf(d["y"], math.exp(a + b * (d["xg"] - mean_x)), k)
                   for d in data)

    best = ll(a, b, k)
    for _ in range(60):
        improved = False
        for param, step in (("a", 0.01), ("b", 0.01), ("k", 0.5)):
            if param == "b" and b_fixed is not None:
                continue
            for sgn in (1, -1):
                cand = {"a": a, "b": b, "k": k}
                cand[param] += sgn * step
                if cand["k"] <= 0.5:
                    continue
                v = ll(cand["a"], cand["b"], cand["k"])
                if v > best + 1e-9:
                    a, b, k = cand["a"], cand["b"], cand["k"]
                    best = v
                    improved = True
        if not improved:
            break
    return a, b, k, mean_x, best


def fit_and_validate():
    rows = list(json.load(open(HIST)).values())
    data = match_xg(rows)
    print(f"\n{len(data)} fixtures with ratings + corners")

    # leave-one-tournament-out: does the xG slope beat intercept-only?
    tot = {"xg": 0.0, "const": 0.0}
    n = 0
    for league, _, _, label in SOURCES:
        train = [d for d in data if d["league"] != label]
        test = [d for d in data if d["league"] == label]
        if not test:
            continue
        for name, bfix in (("xg", None), ("const", 0.0)):
            a, b, k, mx, _ = fit_nb(train, b_fixed=bfix)
            ll = -sum(nb_logpmf(d["y"], math.exp(a + b * (d["xg"] - mx)), k)
                      for d in test) / len(test)
            tot[name] += ll * len(test)
        n += len(test)
        print(f"holdout {label}: n={len(test)}")
    print(f"\nLOTO mean NLL: xG-slope {tot['xg'] / n:.4f} "
          f"vs intercept-only {tot['const'] / n:.4f}")
    use_b = tot["xg"] < tot["const"] - 1e-4
    a, b, k, mx, _ = fit_nb(data, b_fixed=None if use_b else 0.0)
    mus = [math.exp(a + b * (d["xg"] - mx)) for d in data]
    json.dump({"a": a, "b": b, "k": k, "mean_xg": mx,
               "n_fit": len(data), "slope_validated": use_b,
               "loto_nll": {kk: round(v / n, 4) for kk, v in tot.items()},
               "mean_mu": round(sum(mus) / len(mus), 2)},
              open(MODEL, "w"), indent=2)
    print(f"wrote {MODEL} (slope {'KEPT' if use_b else 'REJECTED — intercept only'})")


def predict():
    m = json.load(open(MODEL))
    sims = json.load(open(f"{DATA}/wc26_simulations.json"))["simulations"]
    out = {}
    for mid, s in sims.items():
        mu = math.exp(m["a"] + m["b"] * (s["xg"]["home"] + s["xg"]["away"]
                                         - m["mean_xg"]))
        out[mid] = {"mu": round(mu, 2),
                    **{f"over_{line}": round(nb_cdf_over(line, mu, m["k"]), 4)
                       for line in (7.5, 8.5, 9.5, 10.5, 11.5, 12.5, 13.5)}}
    json.dump({"model": m, "matches": out},
              open(f"{DATA}/wc26_corners.json", "w"), indent=1)
    from wc26_simulate import save_versioned
    save_versioned(f"{DATA}/wc26_corners.json")
    print(f"wrote corner O/U for {len(out)} fixtures")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "fit"
    {"backfill": backfill, "fit": fit_and_validate, "predict": predict}[cmd]()
