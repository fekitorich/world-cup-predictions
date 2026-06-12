"""Falsification test for the squad-value prior (branch experiment).

  python3 wc26_value_test.py

For a grid of beta values: adjust fitted DC ratings by beta * z(log squad
market value), then measure held-out 1X2 log-loss on the 2025-06 -> 2026-06
window. If no beta beats beta=0, the feature is rejected.

Caveat (documented): squad values are today's, used to grade last year's
matches — mild look-ahead, values move slowly.
"""
import json
import math

from wc26_simulate import (ROOT, DATA, SPLIT, params, load_matches, fit, test_set,
                           evaluate)

P = params()
sv = json.load(open(f"{DATA}/wc26_squad_values.json"))
VALUES, DEFAULT = sv["values"], sv["default_for_missing"]

print("fitting base model on data to", SPLIT, "(value prior OFF)...")
model = fit(load_matches(SPLIT, P["half_life"], P["friendly_w"],
                         P["margin_cap"]), P["shrink"], value_beta=0.0)
teams = list(model["att"])

logs = {t: math.log(VALUES.get(t, DEFAULT)) for t in teams}
mu = sum(logs.values()) / len(logs)
sd = math.sqrt(sum((v - mu) ** 2 for v in logs.values()) / len(logs))
z = {t: (logs[t] - mu) / sd for t in teams}
have = sum(1 for t in teams if t in VALUES)
print(f"values for {have}/{len(teams)} rated teams "
      f"(missing teams get the €{DEFAULT}m minnow default)")

test = test_set()
results = {}
for beta in (0.0, 0.05, 0.10, 0.15, 0.20, 0.30, 0.40):
    adj = {
        "att": {t: a + beta * z[t] / 2 for t, a in model["att"].items()},
        "dfn": {t: d - beta * z[t] / 2 for t, d in model["dfn"].items()},
        "mu": model["mu"], "hadv": model["hadv"],
    }
    lls, n = evaluate(adj, test, [P["rho"]])
    results[beta] = lls[P["rho"]]
    print(f"  beta={beta:.2f}  log-loss {lls[P['rho']]:.5f}  (n={n})")

best = min(results, key=results.get)
base = results[0.0]
print(f"\nbest beta = {best}  ({results[best]:.5f} vs {base:.5f} at beta=0, "
      f"delta {results[best] - base:+.5f})")
print("VERDICT:", "value prior HELPS — ship it" if best > 0 and
      results[best] < base - 0.001 else "value prior does NOT clearly help")
