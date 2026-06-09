"""Build a bet plan from model edges vs live Polymarket prices.

  python3 betting/find_bets.py        ->  betting/state/plan.json

Read-only: needs no keys. Pulls fresh prices + CLOB token ids from the
free Gamma API, compares against the RAW model (never the blend — the
blend already contains the market), sizes stakes with fractional Kelly
under the caps in betting/config.json.

Only positive-edge YES buys are planned. Golden Ball / Glove are never
bet (no calibrated model). Review the plan before running place_bets.py.
"""
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
from wc26_polymarket import ALIASES, names_for  # noqa: E402

CFG = json.load(open(f"{HERE}/config.json"))
if os.path.exists(f"{HERE}/config.local.json"):   # gitignored personal caps
    CFG.update(json.load(open(f"{HERE}/config.local.json")))
AWARD_SLUGS = {
    "golden_boot": "world-cup-golden-boot-winner",
    "top_scorer_nation": "world-cup-top-scorer-nation",
}


def gamma(path, **q):
    url = f"https://gamma-api.polymarket.com{path}?" + urllib.parse.urlencode(q)
    req = urllib.request.Request(url, headers={"User-Agent": "wc26-research"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def norm(s):
    import unicodedata
    return unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()


def kelly_stake(q, p, bankroll):
    """Quarter(-ish) Kelly stake for buying YES at price p with belief q."""
    f_star = (q - p) / (1 - p)
    return bankroll * CFG["kelly_fraction"] * f_star


def match_candidates():
    sims = json.load(open(f"{ROOT}/wc26_simulations.json"))["simulations"]
    snap = json.load(open(f"{ROOT}/wc26_market_prices.json"))["prices"]
    out = []
    for mid, rec in snap.items():
        sim = sims.get(mid)
        if not sim:
            continue
        try:
            evs = gamma("/events", slug=rec["slug"])
        except Exception as e:
            print(f"  fetch failed {rec['slug']}: {e}")
            continue
        if not evs:
            continue
        for mk in evs[0]["markets"]:
            ql = mk["question"].lower()
            side = ("draw" if "draw" in ql else
                    "home" if any(f"will {n} win" in ql for n in names_for(sim["home"])) else
                    "away" if any(f"will {n} win" in ql for n in names_for(sim["away"])) else None)
            if not side:
                continue
            try:
                price = float(json.loads(mk["outcomePrices"])[0])
                token = json.loads(mk["clobTokenIds"])[0]   # YES token
            except (KeyError, ValueError, IndexError):
                continue
            q = sim["moneyline"][side]   # RAW model, not blend
            if q - price >= CFG["min_edge_match"]:
                label = {"home": sim["home"], "away": sim["away"], "draw": "Draw"}[side]
                out.append({
                    "category": "moneyline",
                    "bet": f"{sim['home']} v {sim['away']}: {label} (YES)",
                    "question": mk["question"], "token_id": token,
                    "model_p": round(q, 4), "market_p": price,
                    "edge": round(q - price, 4),
                })
        time.sleep(0.12)
    return out


def award_candidates():
    awards = json.load(open(f"{ROOT}/wc26_awards.json"))
    out = []
    model_by_cat = {
        "golden_boot": {norm(b["player"]): b["p_model"] for b in awards["golden_boot"]},
        "top_scorer_nation": {norm(n["team"]): n["p_model"] for n in awards["top_scorer_nation"]},
    }
    for cat, slug in AWARD_SLUGS.items():
        if not CFG["include"].get(cat):
            continue
        evs = gamma("/events", slug=slug)
        for mk in (evs[0]["markets"] if evs else []):
            title = mk.get("groupItemTitle") or ""
            if not title or title == "Other":
                continue
            try:
                price = float(json.loads(mk["outcomePrices"])[0])
                token = json.loads(mk["clobTokenIds"])[0]
            except (KeyError, ValueError, IndexError):
                continue
            # match market name to model name by surname
            last = norm(title).split()[-1]
            qs = [v for k, v in model_by_cat[cat].items()
                  if k.split()[-1] == last or k == norm(title)]
            if len(qs) != 1:
                continue
            q = qs[0]
            if q - price >= CFG["min_edge_award"]:
                out.append({
                    "category": cat, "bet": f"{title} (YES)",
                    "question": mk["question"], "token_id": token,
                    "model_p": round(q, 4), "market_p": price,
                    "edge": round(q - price, 4),
                })
        time.sleep(0.2)
    return out


def main():
    cands = []
    if CFG["include"].get("moneyline"):
        print("scanning match moneylines...", flush=True)
        cands += match_candidates()
    print("scanning award markets...", flush=True)
    cands += award_candidates()
    cands.sort(key=lambda c: -c["edge"])
    cands = cands[:CFG.get("max_bets", 12)]   # concentrate small bankrolls

    bankroll = CFG["max_total_stake_usdc"]
    total = 0.0
    for c in cands:
        stake = min(kelly_stake(c["model_p"], c["market_p"], bankroll),
                    CFG["max_per_bet_usdc"])
        c["stake_usdc"] = round(max(stake, 0), 2)
    cands = [c for c in cands if c["stake_usdc"] >= CFG.get("min_stake_usdc", 1)]
    # scale down if the plan exceeds the total cap
    planned = sum(c["stake_usdc"] for c in cands)
    if planned > bankroll:
        scale = bankroll / planned
        for c in cands:
            c["stake_usdc"] = round(c["stake_usdc"] * scale, 2)
        planned = sum(c["stake_usdc"] for c in cands)
    total = round(planned, 2)

    plan = {
        "created": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "config": CFG,
        "total_planned_usdc": total,
        "bets": cands,
    }
    os.makedirs(f"{HERE}/state", exist_ok=True)
    json.dump(plan, open(f"{HERE}/state/plan.json", "w"), indent=2, ensure_ascii=False)
    print(f"\n{len(cands)} candidate bets, ${total:.2f} planned "
          f"(caps: ${CFG['max_total_stake_usdc']} total / "
          f"${CFG['max_per_bet_usdc']} per bet)")
    for c in cands:
        print(f"  ${c['stake_usdc']:>6.2f}  {c['bet']:<46} "
              f"model {c['model_p']:.2f} vs mkt {c['market_p']:.2f} "
              f"(+{c['edge'] * 100:.1f}¢) [{c['category']}]")
    print(f"\nplan written to betting/state/plan.json — review it, then:\n"
          f"  .venv/bin/python3 betting/place_bets.py            (dry run)\n"
          f"  .venv/bin/python3 betting/place_bets.py --live     (real money)")


if __name__ == "__main__":
    main()
