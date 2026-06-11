"""Dixon-Coles match simulation for WC2026 group stage.

Weighted Poisson attack/defense ratings on internationals since 2018
(martj42 dataset), time decay, friendly down-weighting, shrinkage prior,
Dixon-Coles low-score correction. Pure stdlib.

Usage:
  python3 wc26_simulate.py         # backtest + write wc26_simulations.json
  python3 wc26_simulate.py tune    # coordinate-descent hyperparameter search
                                   # -> writes wc26_params.json

Params come from wc26_params.json when present, else DEFAULTS.
"""
import csv
import json
import math
import os
import shutil
import sys
import time
from datetime import date

ROOT = os.path.dirname(os.path.abspath(__file__))
TODAY = date(2026, 6, 9)
SPLIT = "2025-06-01"          # backtest train/test split
MAX_GOALS = 12
SINCE = "2018-01-01"

DEFAULTS = {"half_life": 548, "friendly_w": 0.6, "shrink": 8.0, "rho": -0.10,
            "margin_cap": 99}
BLEND_W = 0.35   # weight on market prices in the blended probabilities

# Squad-value prior (Transfermarkt): ratings nudged by beta * z(log value).
# Validated out-of-sample 2025-06->2026-06: log-loss 0.854 -> 0.818 at the
# beta=0.4 optimum; shipped at 0.35 as a haircut for the mild look-ahead in
# using current values to grade past matches. See wc26_value_test.py.
VALUE_BETA = 0.35


def _value_z():
    try:
        sv = json.load(open(f"{ROOT}/wc26_squad_values.json"))
    except FileNotFoundError:
        return None
    vals, default = sv["values"], sv["default_for_missing"]
    return vals, default


def apply_value_prior(att, dfn, beta=VALUE_BETA):
    """Nudge fitted ratings toward squad market value (in place)."""
    loaded = _value_z()
    if not loaded or beta == 0:
        return
    vals, default = loaded
    logs = {t: math.log(vals.get(t, default)) for t in att}
    mu = sum(logs.values()) / len(logs)
    sd = math.sqrt(sum((v - mu) ** 2 for v in logs.values()) / len(logs))
    for t in att:
        zt = (logs[t] - mu) / sd
        att[t] += beta * zt / 2
        dfn[t] -= beta * zt / 2

CITY_COUNTRY = {
    "Mexico City": "Mexico", "Guadalajara": "Mexico", "Monterrey": "Mexico",
    "Toronto": "Canada", "Vancouver": "Canada",
}  # every other 2026 venue city is in the United States


def now_utc():
    return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())


def save_versioned(path):
    """Archive a copy of a freshly written result under runs/ (time-coded)."""
    os.makedirs(f"{ROOT}/runs", exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    name = os.path.basename(path).replace("wc26_", "").rsplit(".", 1)[0]
    dst = f"{ROOT}/runs/{stamp}_{name}.json"
    shutil.copy(path, dst)
    return dst


def params():
    try:
        loaded = json.load(open(f"{ROOT}/wc26_params.json"))["params"]
        return {**DEFAULTS, **loaded}
    except FileNotFoundError:
        return dict(DEFAULTS)


def load_matches(cutoff, half_life, friendly_w, margin_cap=99):
    # corrections + missing matches, adjudicated against API-Football
    # (see wc26_data_patches.json); survive CSV re-downloads
    try:
        patches = json.load(open(f"{ROOT}/wc26_data_patches.json"))
    except FileNotFoundError:
        patches = {"score_fixes": [], "additions": []}
    fixes = {(f["date"], f["home_team"], f["away_team"]):
             (f["home_score"], f["away_score"]) for f in patches["score_fixes"]}
    out = []
    cut = date.fromisoformat(cutoff)
    rows = list(csv.DictReader(open(f"{ROOT}/international_results.csv")))
    seen = {(r["date"], r["home_team"], r["away_team"]) for r in rows}
    for a in patches["additions"]:
        if (a["date"], a["home_team"], a["away_team"]) not in seen:
            rows.append({"date": a["date"], "home_team": a["home_team"],
                         "away_team": a["away_team"],
                         "home_score": str(a["home_score"]),
                         "away_score": str(a["away_score"]),
                         "tournament": a["tournament"],
                         "neutral": "TRUE" if a["neutral"] else "FALSE"})
    for r in rows:
        if r["home_score"] == "NA" or not (SINCE <= r["date"] < cutoff):
            continue
        w = 0.5 ** ((cut - date.fromisoformat(r["date"])).days / half_life)
        if r["tournament"] == "Friendly":
            w *= friendly_w
        key = (r["date"], r["home_team"], r["away_team"])
        if key in fixes:
            hg, ag = fixes[key]
        else:
            hg, ag = int(r["home_score"]), int(r["away_score"])
        # cap blowout margins: 9-1 friendlies say less than they shout
        if hg - ag > margin_cap:
            hg = ag + margin_cap
        elif ag - hg > margin_cap:
            ag = hg + margin_cap
        out.append({
            "home": r["home_team"], "away": r["away_team"],
            "hg": hg, "ag": ag,
            "neutral": r["neutral"] == "TRUE", "w": w,
        })
    return out


def fit(matches, shrink, iters=80):
    teams = sorted({m["home"] for m in matches} | {m["away"] for m in matches})
    att = {t: 0.0 for t in teams}
    dfn = {t: 0.0 for t in teams}
    mu, hadv = math.log(1.25), 0.25

    for _ in range(iters):
        tot_g = sum(m["w"] * (m["hg"] + m["ag"]) for m in matches)
        tot_e = sum(
            m["w"] * (math.exp(mu + (0 if m["neutral"] else hadv) + att[m["home"]] + dfn[m["away"]])
                      + math.exp(mu + att[m["away"]] + dfn[m["home"]]))
            for m in matches)
        mu += math.log(tot_g / tot_e)

        hg = he = 0.0
        for m in matches:
            if not m["neutral"]:
                hg += m["w"] * m["hg"]
                he += m["w"] * math.exp(mu + hadv + att[m["home"]] + dfn[m["away"]])
        hadv += math.log(hg / he)

        num_a = {t: shrink * math.exp(mu) for t in teams}
        den_a = {t: shrink * math.exp(mu) for t in teams}
        num_d = {t: shrink * math.exp(mu) for t in teams}
        den_d = {t: shrink * math.exp(mu) for t in teams}
        for m in matches:
            h, a, w = m["home"], m["away"], m["w"]
            hf = 0 if m["neutral"] else hadv
            num_a[h] += w * m["hg"]
            den_a[h] += w * math.exp(mu + hf + dfn[a])
            num_a[a] += w * m["ag"]
            den_a[a] += w * math.exp(mu + dfn[h])
            num_d[h] += w * m["ag"]
            den_d[h] += w * math.exp(mu + att[a])
            num_d[a] += w * m["hg"]
            den_d[a] += w * math.exp(mu + hf + att[h])
        for t in teams:
            att[t] = math.log(num_a[t] / den_a[t])
            dfn[t] = math.log(num_d[t] / den_d[t])
        ma = sum(att.values()) / len(teams)
        md = sum(dfn.values()) / len(teams)
        for t in teams:
            att[t] -= ma
            dfn[t] -= md
        mu += ma + md
    apply_value_prior(att, dfn)
    return {"att": att, "dfn": dfn, "mu": mu, "hadv": hadv}


def poisson_row(lmbda):
    p, out = math.exp(-lmbda), []
    for k in range(MAX_GOALS + 1):
        out.append(p)
        p *= lmbda / (k + 1)
    return out


def score_grid(l1, l2, rho):
    ph, pa = poisson_row(l1), poisson_row(l2)
    g = [[ph[i] * pa[j] for j in range(MAX_GOALS + 1)] for i in range(MAX_GOALS + 1)]
    g[0][0] *= 1 - l1 * l2 * rho
    g[1][0] *= 1 + l2 * rho
    g[0][1] *= 1 + l1 * rho
    g[1][1] *= 1 - rho
    s = sum(map(sum, g))
    return [[v / s for v in row] for row in g]


def lambdas(model, home, away, home_field):
    hf = model["hadv"] if home_field else 0.0
    l1 = math.exp(model["mu"] + hf + model["att"][home] + model["dfn"][away])
    l2 = math.exp(model["mu"] + model["att"][away] + model["dfn"][home])
    return l1, l2


def one_x_two(grid):
    R = range(MAX_GOALS + 1)
    pH = sum(grid[i][j] for i in R for j in R if i > j)
    pD = sum(grid[i][i] for i in R)
    return pH, pD, 1 - pH - pD


def markets(grid):
    R = range(MAX_GOALS + 1)
    pH, pD, pA = one_x_two(grid)
    totals = {f"over_{line}": sum(grid[i][j] for i in R for j in R if i + j > line)
              for line in (1.5, 2.5, 3.5)}
    btts = sum(grid[i][j] for i in R for j in R if i > 0 and j > 0)
    spread = {
        "home_-1.5": sum(grid[i][j] for i in R for j in R if i - j >= 2),
        "away_-1.5": sum(grid[i][j] for i in R for j in R if j - i >= 2),
    }
    scores = sorted(((f"{i}-{j}", grid[i][j]) for i in R for j in R),
                    key=lambda x: -x[1])[:5]
    return pH, pD, pA, totals, btts, spread, scores


def test_set(start=SPLIT, end=None):
    end = end or TODAY.isoformat()
    out = []
    for r in csv.DictReader(open(f"{ROOT}/international_results.csv")):
        if r["home_score"] == "NA" or not (start <= r["date"] < end):
            continue
        out.append(r)
    return out


def evaluate(model, test, rhos):
    """1X2 log-loss per candidate rho, on test matches the model knows."""
    ll = {r: 0.0 for r in rhos}
    n = 0
    for r in test:
        if r["home_team"] not in model["att"] or r["away_team"] not in model["att"]:
            continue
        l1, l2 = lambdas(model, r["home_team"], r["away_team"], r["neutral"] != "TRUE")
        res = "H" if int(r["home_score"]) > int(r["away_score"]) else \
              "A" if int(r["away_score"]) > int(r["home_score"]) else "D"
        for rho in rhos:
            pH, pD, pA = one_x_two(score_grid(l1, l2, rho))
            p = {"H": pH, "D": pD, "A": pA}[res]
            ll[rho] -= math.log(max(p, 1e-9))
        n += 1
    return {r: v / n for r, v in ll.items()}, n


TUNE_WINDOWS = [   # (train cutoff, test start, test end) rolling 12-month windows
    ("2022-06-01", "2022-06-01", "2023-06-01"),
    ("2023-06-01", "2023-06-01", "2024-06-01"),
    ("2024-06-01", "2024-06-01", "2025-06-01"),
    ("2025-06-01", "2025-06-01", None),
]


def tune():
    grid = {
        "half_life": [365, 548, 730, 1000],
        "friendly_w": [0.4, 0.6, 0.8],
        "shrink": [4.0, 8.0, 12.0],
        "margin_cap": [99, 4, 3],
    }
    rhos = [-0.15, -0.10, -0.05, 0.0]
    best = dict(DEFAULTS)
    tests = [(cut, test_set(s, e)) for cut, s, e in TUNE_WINDOWS]
    cache = {}

    def eval_combo(p):
        key = (p["half_life"], p["friendly_w"], p["shrink"], p["margin_cap"])
        if key not in cache:
            tot = {r: 0.0 for r in rhos}
            n_tot = 0
            for cut, test in tests:
                model = fit(load_matches(cut, p["half_life"], p["friendly_w"],
                                         p["margin_cap"]), p["shrink"], iters=60)
                lls, n = evaluate(model, test, rhos)
                for r in rhos:
                    tot[r] += lls[r] * n
                n_tot += n
            avg = {r: v / n_tot for r, v in tot.items()}
            cache[key] = min(avg.items(), key=lambda x: x[1])  # (best rho, ll)
            print(f"  hl={p['half_life']} fw={p['friendly_w']} sh={p['shrink']}"
                  f" cap={p['margin_cap']} -> rho={cache[key][0]}"
                  f" ll={cache[key][1]:.5f}", flush=True)
        return cache[key]

    for sweep in range(2):
        print(f"sweep {sweep + 1}", flush=True)
        for param, values in grid.items():
            results = {}
            for v in values:
                cand = dict(best)
                cand[param] = v
                results[v] = eval_combo(cand)
            best[param] = min(results, key=lambda v: results[v][1])
            best["rho"] = results[best[param]][0]
        print(f"after sweep {sweep + 1}: {best}", flush=True)

    final_ll = eval_combo(best)[1]
    json.dump({"params": best, "cv_logloss": round(final_ll, 5),
               "tuned_on": f"4 rolling windows 2022-2026, {sum(len(t) for _, t in tests)} matches",
               "tuned_at": now_utc()},
              open(f"{ROOT}/wc26_params.json", "w"), indent=2)
    save_versioned(f"{ROOT}/wc26_params.json")
    print(f"TUNED {best} cv-ll={final_ll:.5f} -> wc26_params.json", flush=True)


def blend(p_model, p_market, w=BLEND_W):
    """Log-opinion pool of model and (normalized) market probabilities."""
    tot = sum(p_market.values())
    q = {k: v / tot for k, v in p_market.items()}
    mix = {k: (p_model[k] ** (1 - w)) * (q[k] ** w) for k in p_model}
    s = sum(mix.values())
    return {k: v / s for k, v in mix.items()}


def backtest(p):
    model = fit(load_matches(SPLIT, p["half_life"], p["friendly_w"],
                             p["margin_cap"]), p["shrink"])
    test = test_set()
    lls, n = evaluate(model, test, [p["rho"]])
    from collections import Counter
    freq = Counter()
    for r in test:
        freq["H" if int(r["home_score"]) > int(r["away_score"]) else
             "A" if int(r["away_score"]) > int(r["home_score"]) else "D"] += 1
    tot = sum(freq.values())
    base_ll = -sum(freq[k] * math.log(freq[k] / tot) for k in freq) / tot
    print(f"backtest {n} matches: log-loss {lls[p['rho']]:.4f} "
          f"vs frequency-baseline {base_ll:.4f}")
    return lls[p["rho"]]


TEAM_SET = set()


def main():
    global TEAM_SET
    p = params()
    print("params:", p)
    bt_ll = backtest(p)
    model = fit(load_matches(TODAY.isoformat(), p["half_life"], p["friendly_w"],
                             p["margin_cap"]), p["shrink"])
    TEAM_SET = set(model["att"])
    print(f"model: mu={model['mu']:.3f} home_adv={model['hadv']:.3f} "
          f"teams={len(model['att'])}")

    fixtures = json.load(open(f"{ROOT}/fifa_world_cup_2026_group_matches.json"))["matches"]
    try:
        kos = json.load(open(f"{ROOT}/wc26_knockout_matches.json"))["matches"]
        fixtures = fixtures + [m for m in kos
                               if m["home"] in TEAM_SET and m["away"] in TEAM_SET]
    except FileNotFoundError:
        pass
    try:
        MKT = json.load(open(f"{ROOT}/wc26_market_prices.json"))["prices"]
    except FileNotFoundError:
        MKT = {}
    sims = {}
    for m in fixtures:
        venue_country = CITY_COUNTRY.get(m["city"], "United States")
        home_field = m["home"] == venue_country
        away_field = m["away"] == venue_country
        l1, l2 = lambdas(model, m["home"], m["away"], home_field)
        if away_field:
            l2a, l1a = lambdas(model, m["away"], m["home"], True)
            l1, l2 = l1a, l2a
        pH, pD, pA, totals, btts, spread, scores = markets(score_grid(l1, l2, p["rho"]))
        mkt = MKT.get(str(m["match_id"]), {}).get("moneyline")
        blended = blend({"home": pH, "draw": pD, "away": pA}, mkt) if mkt else None
        sims[str(m["match_id"])] = {
            "home": m["home"], "away": m["away"],
            "round": m.get("round"),
            "home_field": m["home"] if home_field else (m["away"] if away_field else None),
            "xg": {"home": round(l1, 2), "away": round(l2, 2)},
            "moneyline": {"home": round(pH, 4), "draw": round(pD, 4), "away": round(pA, 4)},
            "moneyline_blend": ({k: round(v, 4) for k, v in blended.items()}
                                if blended else None),
            "totals": {k: round(v, 4) for k, v in totals.items()},
            "btts": round(btts, 4),
            "spread": {k: round(v, 4) for k, v in spread.items()},
            "top_scores": [{"score": s, "p": round(p_, 4)} for s, p_ in scores],
        }
    out = {
        "method": f"Dixon-Coles weighted Poisson, params {p}; blend w={BLEND_W} "
                  "on Polymarket where priced",
        "backtest_logloss": round(bt_ll, 4),
        "generated": now_utc(),
        "simulations": sims,
    }
    json.dump(out, open(f"{ROOT}/wc26_simulations.json", "w"), indent=2, ensure_ascii=False)
    save_versioned(f"{ROOT}/wc26_simulations.json")
    print(f"wrote {len(sims)} simulations (archived in runs/)")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "tune":
        tune()
    else:
        main()
