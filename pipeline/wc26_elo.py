"""Elo→goals second-opinion model. ADDITIONAL data, never a replacement.

  python3 pipeline/wc26_elo.py            # backtest + write data/wc26_elo.json
  python3 pipeline/wc26_elo.py tune       # small honest grid over (K, H)

Why it exists: the main model is a 200-member Dixon-Coles ensemble, but
all 200 members share one theory — resample the data and they are wrong
together wherever DC's assumptions are. This model reaches the same
markets through a different structure (sequential Elo ratings with a
margin-aware update, mapped to goal rates by a Poisson regression fitted
on pre-match ratings), so where the two agree the number is sturdier and
where they disagree somebody's assumptions are doing work — that
disagreement is published per match as a tripwire, nothing more.

Hard rules: writes ONLY data/wc26_elo.json. Never touches
wc26_simulations.json, the tournament ensemble, the locked bracket or
the betting scanner (bets keep pricing off the raw DC model). Takes the
SAME exam as DC: train < SPLIT, frozen through the test window,
1X2 log-loss on test_set() — published on the method page either way.
"""
import json
import math
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from wc26_simulate import (ROOT, DATA, TODAY, SPLIT, SINCE, params,   # noqa: E402
                           test_set, score_grid, one_x_two, now_utc,
                           save_versioned)
import csv                                                            # noqa: E402

OUT = f"{DATA}/wc26_elo.json"
START_RATING = 1500.0
K = 64.0          # update size — multi-window tune flattens here; the
                  # grid kept "improving" to K=96 but by <0.002 and
                  # inconsistently across windows (chasing one test year)
H_ELO = 75.0      # home advantage in Elo points (same tune)


def load_chrono(cutoff):
    """Chronological matches with dates — Elo is sequential, so unlike
    fit() it cares about order. Same CSV, same patches as load_matches."""
    try:
        patches = json.load(open(f"{DATA}/wc26_data_patches.json"))
    except FileNotFoundError:
        patches = {"score_fixes": [], "additions": []}
    fixes = {(f["date"], f["home_team"], f["away_team"]):
             (f["home_score"], f["away_score"]) for f in patches["score_fixes"]}
    rows = list(csv.DictReader(open(f"{DATA}/international_results.csv")))
    seen = {(r["date"], r["home_team"], r["away_team"]) for r in rows}
    for a in patches["additions"]:
        if (a["date"], a["home_team"], a["away_team"]) not in seen:
            rows.append({"date": a["date"], "home_team": a["home_team"],
                         "away_team": a["away_team"],
                         "home_score": str(a["home_score"]),
                         "away_score": str(a["away_score"]),
                         "neutral": "TRUE" if a["neutral"] else "FALSE"})
    out = []
    for r in rows:
        if r["home_score"] == "NA" or not (SINCE <= r["date"] < cutoff):
            continue
        key = (r["date"], r["home_team"], r["away_team"])
        hg, ag = fixes.get(key, (int(r["home_score"]), int(r["away_score"])))
        out.append({"date": r["date"], "home": r["home_team"],
                    "away": r["away_team"], "hg": int(hg), "ag": int(ag),
                    "neutral": r["neutral"] == "TRUE"})
    out.sort(key=lambda m: m["date"])
    return out


def expected(r_home, r_away, neutral):
    h = 0.0 if neutral else H_ELO
    return 1.0 / (1.0 + 10 ** (-(r_home + h - r_away) / 400.0))


def margin_mult(hg, ag):
    """Bigger wins move ratings more, with diminishing returns."""
    return math.log1p(abs(hg - ag))


def replay(matches, k=None, h=None):
    """Run Elo through history. Returns (ratings, samples) where samples
    hold the PRE-match state per game — the regression's training rows."""
    global K, H_ELO
    if k is not None:
        K = k
    if h is not None:
        H_ELO = h
    R = {}
    samples = []
    for m in matches:
        ra = R.setdefault(m["home"], START_RATING)
        rb = R.setdefault(m["away"], START_RATING)
        samples.append({"diff": ra - rb, "neutral": m["neutral"],
                        "hg": m["hg"], "ag": m["ag"]})
        e = expected(ra, rb, m["neutral"])
        s = 1.0 if m["hg"] > m["ag"] else 0.0 if m["hg"] < m["ag"] else 0.5
        delta = K * (margin_mult(m["hg"], m["ag"]) or 0.5) * (s - e)
        R[m["home"]] = ra + delta
        R[m["away"]] = rb - delta
    return R, samples


def fit_goals(samples, iters=400):
    """Poisson regression of goals on the pre-match rating gap:
      log E[home goals] = a + b*(diff/400) + c*home_field
      log E[away goals] = a - b*(diff/400)
    Coordinate grid descent, stdlib-only (project idiom)."""
    a, b, c = math.log(1.25), 0.5, 0.25

    def ll(a, b, c):
        t = 0.0
        for s in samples:
            d = s["diff"] / 400.0
            hf = 0.0 if s["neutral"] else c
            l1, l2 = math.exp(a + b * d + hf), math.exp(a - b * d)
            t += s["hg"] * (a + b * d + hf) - l1
            t += s["ag"] * (a - b * d) - l2
        return t

    best = ll(a, b, c)
    step = {"a": 0.02, "b": 0.02, "c": 0.02}
    for _ in range(iters):
        improved = False
        for p in ("a", "b", "c"):
            for sgn in (1, -1):
                cand = {"a": a, "b": b, "c": c}
                cand[p] += sgn * step[p]
                v = ll(**cand)
                if v > best + 1e-9:
                    a, b, c = cand["a"], cand["b"], cand["c"]
                    best, improved = v, True
        if not improved:
            for p in step:
                step[p] /= 2
            if max(step.values()) < 1e-4:
                break
    return {"a": a, "b": b, "c": c}


def lambdas_elo(R, g, home, away, home_field):
    d = (R[home] - R[away]) / 400.0
    l1 = math.exp(g["a"] + g["b"] * d + (g["c"] if home_field else 0.0))
    l2 = math.exp(g["a"] - g["b"] * d)
    return l1, l2


def backtest(k=None, h=None, quiet=False, cutoff=SPLIT, start=None, end=None):
    """The same exam DC takes: ratings + regression frozen at the cutoff,
    1X2 log-loss on every later match both models know."""
    rho = params()["rho"]
    R, samples = replay(load_chrono(cutoff), k, h)
    g = fit_goals(samples)
    ll = n = 0
    for r in test_set(start or cutoff, end):
        if r["home_team"] not in R or r["away_team"] not in R:
            continue
        l1, l2 = lambdas_elo(R, g, r["home_team"], r["away_team"],
                             r["neutral"] != "TRUE")
        pH, pD, pA = one_x_two(score_grid(l1, l2, rho))
        res = "H" if int(r["home_score"]) > int(r["away_score"]) else \
              "A" if int(r["away_score"]) > int(r["home_score"]) else "D"
        ll -= math.log(max({"H": pH, "D": pD, "A": pA}[res], 1e-9))
        n += 1
    out = ll / n
    if not quiet:
        print(f"elo backtest K={K:.0f} H={H_ELO:.0f}: {n} matches, "
              f"1X2 log-loss {out:.4f}  "
              f"(goals map a={g['a']:.3f} b={g['b']:.3f} c={g['c']:.3f})")
    return out, n


def compare():
    """Head-to-head on the IDENTICAL test matches (both models must know
    both teams) — the only fair comparison — plus a 50/50 log-opinion
    blend preview. Promotion to the published numbers needs the blend to
    beat DC alone here, validated, not vibes."""
    from wc26_simulate import fit, load_matches, lambdas
    p = params()
    dc = fit(load_matches(SPLIT, p["half_life"], p["friendly_w"],
                          p["margin_cap"]), p["shrink"])
    R, samples = replay(load_chrono(SPLIT))
    g = fit_goals(samples)
    lls = {"dc": 0.0, "elo": 0.0, "blend": 0.0}
    n = 0
    for r in test_set():
        ht, at = r["home_team"], r["away_team"]
        if ht not in dc["att"] or at not in dc["att"] \
                or ht not in R or at not in R:
            continue
        hf = r["neutral"] != "TRUE"
        probs = {}
        l1, l2 = lambdas(dc, ht, at, hf)
        probs["dc"] = one_x_two(score_grid(l1, l2, p["rho"]))
        e1, e2 = lambdas_elo(R, g, ht, at, hf)
        probs["elo"] = one_x_two(score_grid(e1, e2, p["rho"]))
        gm = [math.sqrt(a * b) for a, b in zip(probs["dc"], probs["elo"])]
        probs["blend"] = tuple(x / sum(gm) for x in gm)
        res = 0 if int(r["home_score"]) > int(r["away_score"]) else \
            2 if int(r["away_score"]) > int(r["home_score"]) else 1
        for k in lls:
            lls[k] -= math.log(max(probs[k][res], 1e-9))
        n += 1
    print(f"same {n} test matches (both models rate both teams):")
    for k in ("dc", "elo", "blend"):
        print(f"  {k:<6} 1X2 log-loss {lls[k] / n:.4f}")


def tune():
    """Average over the same rolling 12-month windows DC was tuned on —
    one lucky test year must not pick the constants."""
    from wc26_simulate import TUNE_WINDOWS
    print("honest grid, averaged over rolling windows (train < each "
          "cutoff only):")
    best = None
    for k in (24, 32, 48, 64, 80, 96):
        for h in (50, 75, 100):
            lls = [backtest(k, h, quiet=True, cutoff=c, start=s, end=e)[0]
                   for c, s, e in TUNE_WINDOWS]
            avg = sum(lls) / len(lls)
            print(f"  K={k:<3} H={h:<4} avg {avg:.4f}  "
                  f"({'  '.join(f'{x:.4f}' for x in lls)})")
            if best is None or avg < best[0]:
                best = (avg, k, h)
    print(f"best: K={best[1]} H={best[2]} (avg {best[0]:.4f}) — "
          f"update the constants in this file if you adopt them")


def predict():
    """Full-history fit, second-opinion numbers for the 72 fixtures, and
    the per-match disagreement vs the canonical DC simulations."""
    rho = params()["rho"]
    ll_elo, n_test = backtest(quiet=True)
    R, samples = replay(load_chrono(TODAY.isoformat()))
    g = fit_goals(samples)
    sims = json.load(open(f"{DATA}/wc26_simulations.json"))["simulations"]
    fx = json.load(open(f"{DATA}/fifa_world_cup_2026_group_matches.json"))
    matches = {}
    for m in fx["matches"]:
        mid = str(m["match_id"])
        sim = sims.get(mid)
        if not sim or m["home"] not in R or m["away"] not in R:
            continue
        l1, l2 = lambdas_elo(R, g, m["home"], m["away"],
                             sim.get("home_field", False))
        pH, pD, pA = one_x_two(score_grid(l1, l2, rho))
        dc = sim["moneyline"]
        disagree = max(abs(pH - dc["home"]), abs(pD - dc["draw"]),
                       abs(pA - dc["away"]))
        matches[mid] = {
            "moneyline": {"home": round(pH, 4), "draw": round(pD, 4),
                          "away": round(pA, 4)},
            "xg": {"home": round(l1, 2), "away": round(l2, 2)},
            "elo": {"home": round(R[m["home"]]), "away": round(R[m["away"]])},
            "disagreement": round(disagree, 4),
        }
    payload = {
        "generated": now_utc(),
        "method": "Elo (margin-aware K) -> Poisson goals map -> same DC "
                  "grid; structurally independent second opinion, "
                  "display-only",
        "params": {"K": K, "H_elo": H_ELO, "rho": rho, "goals_map": g},
        "backtest": {"logloss_1x2": round(ll_elo, 4), "n": n_test,
                     "split": SPLIT},
        "top_ratings": dict(sorted(((t, round(r)) for t, r in R.items()),
                                   key=lambda kv: -kv[1])[:20]),
        "matches": matches,
    }
    json.dump(payload, open(OUT, "w"), indent=1, ensure_ascii=False)
    save_versioned(OUT)
    big = [m for m in matches.values() if m["disagreement"] >= 0.08]
    print(f"elo second opinion: {len(matches)} fixtures, backtest log-loss "
          f"{ll_elo:.4f} on {n_test}, {len(big)} fixture(s) disagree "
          f"with DC by >=8pp -> {OUT}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "tune":
        tune()
    elif len(sys.argv) > 1 and sys.argv[1] == "compare":
        compare()
    else:
        predict()
