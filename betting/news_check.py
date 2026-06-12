"""LLM news gate for the betting plan — facts in, flags out, never odds.

  .venv/bin/python3 betting/news_check.py             # gate the current plan
  .venv/bin/python3 betting/news_check.py --limit 2   # first N dossiers only
  .venv/bin/python3 betting/news_check.py holdings    # sell-flags for ledger

plan mode (default): for every fixture/award in betting/state/plan.json,
build a dossier — API-Football injuries + confirmed lineups, Open-Meteo
stadium weather, our model numbers and planned stakes — and have the
analyst (claude-opus-4-8 + web search) flag each planned bet:
  clear   nothing material found
  caution credible-but-unconfirmed concern -> stake * news_caution_factor
  veto    confirmed info that breaks the bet's premise -> removed
Bets whose edge >= news_big_edge_cents get an explicit "why does the
market disagree?" investigation — a fat edge the news can explain is a
trap, not an opinion.

holdings mode: same dossiers for every OPEN ledger position; flags
hold / review / sell_flag. Prints and logs only — never trades.

Hard rules, enforced in code not prompts: the LLM can only block or
shrink bets — never add one, never raise a stake, never touch a price.
If the analyst fails (no key, refusal, junk output) the plan passes
through UNCHANGED with a loud warning: the gate must never fail into
silently different stakes. Key absences are also translated into an
ADVISORY adjusted moneyline (scaled lambdas through the same DC grid);
it is applied to plan edges only when apply_lineup_adjustments is true,
which ships false (test-enforced) until the flag log earns it.
Every run is appended to betting/state/news_checks.json for grading.
"""
import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
DATA = os.path.join(ROOT, "data")
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
from find_bets import merge_local                     # noqa: E402
from wc26_llm import api_key                          # noqa: E402

CFG = json.load(open(f"{HERE}/config.json"))
if os.path.exists(f"{HERE}/config.local.json"):
    CFG = merge_local(CFG, json.load(open(f"{HERE}/config.local.json")))

MODEL = "claude-opus-4-8"
LOG = f"{HERE}/state/news_checks.json"
PLAN = f"{HERE}/state/plan.json"

PLAN_FLAGS = ("clear", "caution", "veto")
HOLD_FLAGS = ("hold", "review", "sell_flag")

SYSTEM = """You are a pre-bet risk analyst for a statistical football model.
The model is pure Dixon-Coles on results history: it knows NOTHING about
injuries, suspensions, confirmed lineups, rotation, weather or any news.
Your only job is to find recent, credible information that the model
cannot see and translate it into per-bet flags. You never estimate
probabilities and never suggest bets.

Flag meanings (be conservative — most bets should be "clear"):
- veto: confirmed information that breaks the bet's premise (key player
  for the side we back is out; heavy confirmed rotation; abandoned/moved
  match). Requires a citable source.
- caution: credible but unconfirmed concern (doubtful star, strong
  rotation rumours, severe weather forecast for kickoff).
- clear: nothing material.
For bets marked needs_market_check, search specifically for why the
market might disagree with the model; report what the market may know.

Respond with STRICT JSON only — no prose before or after:
{"flags": [{"bet": "<exact bet string>", "flag": "<flag>",
            "reasons": ["short fact + source"]}],
 "key_absences": [{"team": "", "player": "", "status": "confirmed|doubtful"}],
 "market_knows": "none|maybe|likely",
 "summary": "<=50 words"}"""


# ---------------- data gathering ----------------
def af(path):
    key = (os.environ.get("API_FOOTBALL_KEY")
           or open(os.path.join(ROOT, ".api_football_key")).read().strip())
    req = urllib.request.Request(f"https://v3.football.api-sports.io/{path}",
                                 headers={"x-apisports-key": key})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["response"]


def injuries(fixture_id):
    try:
        return [{"player": i["player"]["name"], "team": i["team"]["name"],
                 "type": i["player"].get("type"),
                 "reason": i["player"].get("reason")}
                for i in af(f"injuries?fixture={fixture_id}")]
    except Exception as e:
        print(f"  injuries fetch failed: {e}")
        return []


def lineups(fixture_id):
    try:
        return [{"team": t["team"]["name"],
                 "formation": t.get("formation"),
                 "startXI": [p["player"]["name"]
                             for p in (t.get("startXI") or [])]}
                for t in af(f"fixtures/lineups?fixture={fixture_id}")]
    except Exception as e:
        print(f"  lineups fetch failed: {e}")
        return []


_geo = {}


def weather(city, kickoff_iso):
    """Stadium-city forecast at the hour nearest kickoff (Open-Meteo, free)."""
    try:
        if city not in _geo:
            q = urllib.parse.quote(city)
            with urllib.request.urlopen(
                    "https://geocoding-api.open-meteo.com/v1/search?count=1&name="
                    + q, timeout=15) as r:
                hit = (json.load(r).get("results") or [None])[0]
            _geo[city] = (hit["latitude"], hit["longitude"]) if hit else None
        if not _geo[city]:
            return None
        lat, lon = _geo[city]
        url = (f"https://api.open-meteo.com/v1/forecast?latitude={lat}"
               f"&longitude={lon}&hourly=temperature_2m,"
               f"precipitation_probability,wind_speed_10m"
               f"&forecast_days=7&timezone=UTC")
        with urllib.request.urlopen(url, timeout=15) as r:
            h = json.load(r)["hourly"]
        want = kickoff_iso[:13]            # YYYY-MM-DDTHH
        idx = next((i for i, t in enumerate(h["time"])
                    if t[:13] == want), None)
        if idx is None:
            return None
        return {"temp_c": h["temperature_2m"][idx],
                "precip_pct": h["precipitation_probability"][idx],
                "wind_kmh": h["wind_speed_10m"][idx]}
    except Exception as e:
        print(f"  weather fetch failed: {e}")
        return None


# ---------------- advisory lineup adjustment ----------------
def goal_share(team, player):
    """Player's share of his squad's international goals (0 if unknown)."""
    try:
        squad = json.load(open(f"{DATA}/wc26_players.json"))["squads"][team]
    except (FileNotFoundError, KeyError):
        return 0.0
    total = sum(p.get("goals", 0) for p in squad) or 1
    last = player.split()[-1].lower()
    for p in squad:
        if p["name"].split()[-1].lower() == last:
            return p.get("goals", 0) / total
    return 0.0


def adjusted_moneyline(xg, scale_home=1.0, scale_away=1.0):
    """Re-run the fitted lambdas through the same DC grid with a side's
    attack scaled down — what the moneyline WOULD be without the player."""
    from wc26_simulate import score_grid, one_x_two
    g = score_grid(xg["home"] * scale_home, xg["away"] * scale_away,
                   rho=-0.08)
    h, d, a = one_x_two(g)
    return {"home": round(h, 4), "draw": round(d, 4), "away": round(a, 4)}


def absence_advisories(report, sim):
    """Advisory only: adjusted moneyline for confirmed key absences."""
    out = []
    for ab in report.get("key_absences", []):
        if ab.get("status") != "confirmed":
            continue
        for side in ("home", "away"):
            if ab.get("team") == sim.get(side):
                share = goal_share(sim[side], ab.get("player", ""))
                if share <= 0:
                    continue
                adj = adjusted_moneyline(
                    sim["xg"],
                    scale_home=1 - share if side == "home" else 1.0,
                    scale_away=1 - share if side == "away" else 1.0)
                out.append({"team": sim[side], "player": ab["player"],
                            "goal_share": round(share, 3),
                            "moneyline_before": sim["moneyline"],
                            "moneyline_adjusted": adj})
    return out


# ---------------- LLM plumbing ----------------
def client():
    import anthropic
    return anthropic.Anthropic(api_key=api_key())


def extract_json(text):
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("no JSON object in analyst output")
    return json.loads(text[start:end + 1])


def validate_report(obj, expected_bets, flags=PLAN_FLAGS):
    """The analyst can only speak about bets we showed it, with flags we
    defined. Unknown bets are dropped; unknown flags become the safest
    default for their mode; bets it ignored default to that too."""
    default = flags[0]
    out = {b: (default, []) for b in expected_bets}
    for f in (obj or {}).get("flags", []):
        bet = f.get("bet")
        if bet not in out:
            continue
        flag = f.get("flag") if f.get("flag") in flags else default
        reasons = [str(r) for r in (f.get("reasons") or [])][:4]
        out[bet] = (flag, reasons)
    return out


def apply_flags(bets, flag_map, cfg):
    """Code applies what the analyst found. Reduce-only by construction:
    veto removes, caution scales down, anything else changes nothing."""
    factor = cfg.get("news_caution_factor", 0.5)
    kept, dropped, scaled = [], [], []
    for b in bets:
        flag, reasons = flag_map.get(b["bet"], ("clear", []))
        if flag == "veto":
            dropped.append({**b, "news_reasons": reasons})
            continue
        if flag == "caution":
            b = {**b, "stake_usdc": round(b["stake_usdc"] * factor, 2),
                 "news_flag": "caution", "news_reasons": reasons}
            if b["stake_usdc"] < 1:
                dropped.append(b)
                continue
            scaled.append(b["bet"])
        kept.append(b)
    return kept, dropped, scaled


def ask(cl, dossier, system=SYSTEM):
    msg = cl.messages.create(
        model=MODEL, max_tokens=4000,
        thinking={"type": "adaptive"},
        system=[{"type": "text", "text": system,
                 "cache_control": {"type": "ephemeral"}}],
        messages=[{"role": "user", "content": json.dumps(
            dossier, ensure_ascii=False)}],
        tools=[{"type": "web_search_20250305", "name": "web_search",
                "max_uses": CFG.get("news_max_searches", 4)}],
    )
    if msg.stop_reason == "refusal":
        raise RuntimeError("analyst refused")
    text = "".join(b.text for b in msg.content
                   if getattr(b, "type", "") == "text")
    return extract_json(text)


# ---------------- dossiers ----------------
def fixture_dossiers(bets, mode):
    """Group plan/ledger bets by fixture; awards get their own dossier."""
    sims = json.load(open(f"{DATA}/wc26_simulations.json"))["simulations"]
    fx = {str(m["match_id"]): m for m in json.load(open(
        f"{DATA}/fifa_world_cup_2026_group_matches.json"))["matches"]}
    by_teams = {(s["home"], s["away"]): mid for mid, s in sims.items()}
    big = CFG.get("news_big_edge_cents", 15) / 100

    groups, awards = {}, []
    for b in bets:
        if b["category"] in ("golden_boot", "top_scorer_nation"):
            awards.append(b)
            continue
        mid = str(b.get("match_id") or "")
        if mid not in sims and " v " in b.get("bet", ""):
            teams = b["bet"].split(": ")[0]
            mid = by_teams.get(tuple(teams.split(" v ")), "")
        if mid in sims:
            groups.setdefault(mid, []).append(b)

    out = []
    for mid, group in groups.items():
        sim, f = sims[mid], fx.get(mid, {})
        kickoff = f.get("date_utc", "")
        out.append((mid, sim, {
            "task": ("flag each planned bet" if mode == "plan"
                     else "flag each OPEN position we already hold"),
            "allowed_flags": list(PLAN_FLAGS if mode == "plan"
                                  else HOLD_FLAGS),
            "fixture": f"{sim['home']} v {sim['away']}",
            "kickoff_utc": kickoff, "venue": f.get("venue"),
            "city": f.get("city"),
            "weather_at_kickoff": weather(f.get("city") or "", kickoff),
            "injuries_api": injuries(int(mid)) if mid.isdigit() else [],
            "confirmed_lineups": lineups(int(mid)) if mid.isdigit() else [],
            "model": {"moneyline": sim["moneyline"], "xg": sim["xg"]},
            "our_bets": [{
                "bet": b["bet"],
                "stake_usdc": b.get("stake_usdc"),
                "model_p": b.get("model_p"), "market_p": b.get("market_p",
                                                               b.get("price_seen")),
                "needs_market_check":
                    (b.get("model_p", 0)
                     - b.get("market_p", b.get("price_seen", 0))) >= big,
            } for b in group],
        }))
    for b in awards:
        out.append((f"award:{b['bet']}", None, {
            "task": ("flag this planned award bet" if mode == "plan"
                     else "flag this OPEN award position"),
            "allowed_flags": list(PLAN_FLAGS if mode == "plan"
                                  else HOLD_FLAGS),
            "award_market": b["category"],
            "context": "tournament-long bet; search for injury/role news "
                       "about the player (or the nation's main strikers)",
            "our_bets": [{"bet": b["bet"], "stake_usdc": b.get("stake_usdc"),
                          "model_p": b.get("model_p"),
                          "market_p": b.get("market_p", b.get("price_seen")),
                          "needs_market_check": True}],
        }))
    return out


def log_run(mode, reports, applied):
    try:
        log = json.load(open(LOG))
    except FileNotFoundError:
        log = {"runs": []}
    log["runs"].append({
        "at": time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime()),
        "mode": mode, "model": MODEL, "reports": reports,
        "applied": applied})
    os.makedirs(f"{HERE}/state", exist_ok=True)
    json.dump(log, open(LOG, "w"), indent=1, ensure_ascii=False)
    try:   # keep the local report page in sync with every run
        import news_report
        news_report.main()
    except Exception as e:
        print(f"  report render failed (log intact): {e}")


# ---------------- modes ----------------
def run_plan(limit=None):
    plan = json.load(open(PLAN))
    bets = plan["bets"]
    if not bets:
        print("plan is empty — nothing to check")
        return
    if not api_key():
        print("WARNING: no Anthropic key — news gate SKIPPED, plan unchanged")
        return
    cl = client()
    sims = json.load(open(f"{DATA}/wc26_simulations.json"))["simulations"]
    dossiers = fixture_dossiers(bets, "plan")
    if limit:
        dossiers = dossiers[:limit]
    flag_map, reports, failed = {}, [], 0
    for mid, sim, d in dossiers:
        label = d.get("fixture") or d["our_bets"][0]["bet"]
        print(f"checking {label} ...", flush=True)
        try:
            rep = ask(cl, d)
        except Exception as e:
            print(f"  ANALYST FAILED ({e}) — bets pass through unchanged")
            failed += 1
            continue
        fm = validate_report(rep, [b["bet"] for b in d["our_bets"]])
        flag_map.update(fm)
        advisories = absence_advisories(rep, sim) if sim else []
        reports.append({"dossier_id": mid, "fixture": label,
                        "report": rep, "advisories": advisories})
        for bet, (flag, reasons) in fm.items():
            if flag != "clear":
                print(f"  {flag.upper()}: {bet} — {'; '.join(reasons)}")
        for adv in advisories:
            print(f"  advisory: without {adv['player']} "
                  f"({adv['goal_share']:.0%} of {adv['team']} goals) "
                  f"moneyline {adv['moneyline_before']} -> "
                  f"{adv['moneyline_adjusted']}"
                  + ("" if CFG.get("apply_lineup_adjustments")
                     else " [NOT applied]"))

    kept, dropped, scaled = apply_flags(bets, flag_map, CFG)
    plan["bets"] = kept
    plan["total_planned_usdc"] = round(
        sum(b["stake_usdc"] for b in kept), 2)
    plan["news_checked"] = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    json.dump(plan, open(PLAN, "w"), indent=2, ensure_ascii=False)
    log_run("plan", reports, {
        "dropped": [b["bet"] for b in dropped], "scaled": scaled,
        "analyst_failures": failed})
    print(f"\nnews gate: {len(kept)} bets kept, {len(dropped)} removed, "
          f"{len(scaled)} stakes reduced"
          + (f", {failed} dossiers unchecked (analyst failed)" if failed
             else ""))
    print(f"plan rewritten ({PLAN}); log: betting/state/news_checks.json")


def run_holdings(limit=None):
    try:
        led = json.load(open(f"{HERE}/state/ledger.json"))["placed"]
    except FileNotFoundError:
        print("no ledger — nothing held")
        return
    if not api_key():
        print("no Anthropic key — cannot review holdings")
        return
    cl = client()
    dossiers = fixture_dossiers(led, "holdings")
    if limit:
        dossiers = dossiers[:limit]
    reports, flagged = [], []
    for mid, sim, d in dossiers:
        label = d.get("fixture") or d["our_bets"][0]["bet"]
        print(f"reviewing {label} ...", flush=True)
        try:
            rep = ask(cl, d)
        except Exception as e:
            print(f"  ANALYST FAILED ({e})")
            continue
        fm = validate_report(rep, [b["bet"] for b in d["our_bets"]],
                             flags=HOLD_FLAGS)
        reports.append({"dossier_id": mid, "fixture": label, "report": rep})
        for bet, (flag, reasons) in fm.items():
            if flag != "hold":
                flagged.append((flag, bet, reasons))
                print(f"  {flag.upper()}: {bet} — {'; '.join(reasons)}")
    log_run("holdings", reports, {"flagged": [list(f) for f in flagged]})
    print(f"\nholdings review: {len(flagged)} position(s) flagged "
          f"(nothing is ever sold automatically); "
          f"log: betting/state/news_checks.json")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", nargs="?", default="plan",
                    choices=["plan", "holdings"])
    ap.add_argument("--limit", type=int, default=None,
                    help="check at most N dossiers (cost control)")
    args = ap.parse_args()
    if args.mode == "plan":
        run_plan(args.limit)
    else:
        run_holdings(args.limit)


if __name__ == "__main__":
    main()
