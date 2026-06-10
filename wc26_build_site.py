"""Build the WC2026 Form Book static site from the two data JSONs.

Reads:  fifa_world_cup_2026.json, fifa_world_cup_2026_group_matches.json
Writes: wc26_site/  (index.html, matches.html, teams/*.html, matches/*.html, style.css)

Re-run after refreshing data; output is fully regenerated.
"""
import json
import re
import shutil
from html import escape
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "docs"   # served by GitHub Pages (main branch /docs)
BUILD_V = datetime.now(timezone.utc).strftime("%Y%m%d%H%M")  # css cache-buster

teams_data = json.load(open(ROOT / "fifa_world_cup_2026.json"))
matches_data = json.load(open(ROOT / "fifa_world_cup_2026_group_matches.json"))
try:
    _sim = json.load(open(ROOT / "wc26_simulations.json"))
    SIMS, SIM_LOGLOSS = _sim["simulations"], _sim.get("backtest_logloss")
    SIM_AT = _sim.get("generated")
except FileNotFoundError:
    SIMS, SIM_LOGLOSS, SIM_AT = {}, None, None
try:
    _mkt = json.load(open(ROOT / "wc26_market_prices.json"))
    PRICES, PRICES_AT = _mkt["prices"], _mkt["fetched_at"]
except FileNotFoundError:
    PRICES, PRICES_AT = {}, None
try:
    TOURNEY = json.load(open(ROOT / "wc26_tournament.json"))["teams"]
except FileNotFoundError:
    TOURNEY = {}
try:
    PRED = json.load(open(ROOT / "wc26_predictions.json"))
except FileNotFoundError:
    PRED = None
try:
    AWARDS = json.load(open(ROOT / "wc26_awards.json"))
except FileNotFoundError:
    AWARDS = None

TEAMS = {t["country"]: t for t in teams_data["teams"]}
MATCHES = matches_data["matches"]

team_group = {}
for m in MATCHES:
    team_group[m["home"]] = m["group"]
    team_group[m["away"]] = m["group"]


def slug(name):
    return re.sub(r"[^a-z0-9]+", "-", name.lower().replace("ç", "c")).strip("-")


def match_slug(m):
    return f"{slug(m['home'])}-vs-{slug(m['away'])}"


def fmt_date(iso):
    dt = datetime.fromisoformat(iso)
    return dt.strftime("%-d %b %Y"), dt.strftime("%H:%M")


def stats(team):
    ms = team["last_10_matches"]
    w = sum(1 for m in ms if m["result"] == "W")
    d = sum(1 for m in ms if m["result"] == "D")
    l = sum(1 for m in ms if m["result"] == "L")
    gf = ga = o25 = btts = cs = 0
    for m in ms:
        f, a = (int(x) for x in m["score"].split("-"))
        gf += f
        ga += a
        if f + a > 2:
            o25 += 1
        if f > 0 and a > 0:
            btts += 1
        if a == 0:
            cs += 1
    n = len(ms) or 1
    return {
        "record": f"{w}–{d}–{l}",
        "gf_pg": gf / n, "ga_pg": ga / n,
        "cs": cs, "o25": o25, "btts": btts, "n": len(ms),
    }


def form_chips(team, count=5):
    chips = "".join(
        f'<i class="f {m["result"]}">{m["result"]}</i>'
        for m in team["last_10_matches"][:count]
    )
    tip = (f"last {count} internationals, most recent first — "
           "W win, D draw (incl. pen shoot-outs), L loss")
    return f'<span class="form" title="{tip}">{chips}</span>'


def team_link(name, depth=0):
    pre = "../" * depth
    t = TEAMS[name]
    return f'<a class="tlink" href="{pre}teams/{slug(name)}.html">{escape(name)}</a>'


def page(title, body, depth=0, crumb=""):
    pre = "../" * depth
    # our title= attrs become CSS tooltips (instant, styled, tap-friendly)
    body = body.replace(' title="', ' data-tip="')
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)} · WC26 Form Book</title>
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Ccircle cx='8' cy='8' r='7' fill='%23211d16'/%3E%3Cpath d='M8 4l3 2.2-1.1 3.6H6.1L5 6.2z' fill='%23f6f1e6'/%3E%3C/svg%3E">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Fraunces:opsz,wght@9..144,400;9..144,600;9..144,900&family=IBM+Plex+Mono:wght@400;500;600&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{pre}style.css?v={BUILD_V}">
</head>
<body>
<header class="masthead">
  <div class="kicker">The Form Book — research edition</div>
  <a class="wordmark" href="{pre}index.html">World&nbsp;Cup&nbsp;26</a>
  <nav><a href="{pre}index.html">Groups</a><span>·</span><a href="{pre}matches.html">Matches</a><span>·</span><a href="{pre}futures.html">Futures</a><span>·</span><a href="{pre}awards.html">Awards</a><span>·</span><a href="{pre}bracket.html">Bracket</a></nav>
</header>
{f'<div class="crumb">{crumb}</div>' if crumb else ''}
<main>
{body}
</main>
<footer>
  <p>Form chips read most-recent first. Stats computed over each team's last 10 completed internationals.</p>
  <p>Model run: {SIM_AT or "—"} · Polymarket snapshot: {PRICES_AT or "—"} · every run archived in runs/</p>
  <p>Data: API-Football · FIFA rankings June 2026 · personal research, verify before staking.</p>
</footer>
</body>
</html>"""


# ---------- index: group tables ----------
def build_index():
    groups = {}
    for name, g in team_group.items():
        groups.setdefault(g, []).append(name)

    cards = []
    for g in sorted(groups):
        rows = []
        for name in sorted(groups[g], key=lambda n: TEAMS[n]["fifa_ranking"]):
            t = TEAMS[name]
            host = ' <sup class="host">host</sup>' if t.get("host") else ""
            rows.append(
                f"<tr><td>{team_link(name)}{host}</td>"
                f'<td class="num">{t["fifa_ranking"]}</td>'
                f"<td>{form_chips(t)}</td></tr>"
            )
        cards.append(f"""<section class="group">
<h2><span>Group</span> {g}</h2>
<table>
<thead><tr><th>Team</th><th class="num" title="official FIFA ranking, 1 Apr 2026 — shown for orientation; the model does not use it">FIFA</th><th title="last 5 internationals, most recent first — W win, D draw (pens count as draws), L loss">Form</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</section>""")

    body = f"""<h1>The twelve groups</h1>
<p class="standfirst">48 teams, seeded here by FIFA ranking. Click any team for its full dossier.</p>
<p class="fineprint">Form = results of the last five internationals, <b>most recent first</b>
(W win, D draw — penalty shoot-outs count as draws, L loss); the team page shows all ten with
opponents and competitions. Friendlies are included here but weigh less in the model.
The FIFA column is the official 1 April 2026 ranking, shown for orientation only —
the simulation rates teams purely from match results and disagrees in places (France is FIFA #1
but mid-pack by title odds; the model prefers recent goals to reputation). The <sup class="host">host</sup>
marker matters beyond ceremony: hosts get a fitted home-crowd boost (~+30% scoring) whenever they
play in their own country, which is most of their matches.</p>
<div class="groups">{''.join(cards)}</div>"""
    (OUT / "index.html").write_text(page("Groups", body))


# ---------- matches list ----------
def build_matches_list():
    by_day = {}
    for m in MATCHES:
        by_day.setdefault(m["date_utc"][:10], []).append(m)

    sections = []
    for day in sorted(by_day):
        date_label, _ = fmt_date(by_day[day][0]["date_utc"])
        rows = []
        for m in sorted(by_day[day], key=lambda x: x["date_utc"]):
            _, time_ = fmt_date(m["date_utc"])
            rows.append(f"""<tr>
<td class="num">{time_}</td>
<td><b class="gchip">{m['group']}</b></td>
<td class="fixture"><a href="matches/{match_slug(m)}.html">{escape(m['home'])} <em>v</em> {escape(m['away'])}</a></td>
<td class="venue">{escape(m['venue'])}, {escape(m['city'])}</td>
</tr>""")
        sections.append(f"""<section class="matchday">
<h2>{date_label}</h2>
<table>
<thead><tr><th class="num" title="kick-off time, UTC — 00:00-02:00 games are US/Mexico evenings">UTC</th><th title="group A-L">Grp</th><th>Fixture</th><th>Venue</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>
</section>""")

    body = f"""<h1>Group stage — all 72 fixtures</h1>
<p class="standfirst">Every match links to a head-to-head card comparing both teams' last ten.</p>
<p class="fineprint">Kick-offs are UTC — the 00:00–02:00 oddities are evening games in US/Mexico time
zones, landing a calendar day later than the local date Polymarket uses in its market slugs.
On matchday 3 both games in a group kick off simultaneously (FIFA's anti-collusion rule since 1982),
so their in-play prices move together.</p>
{''.join(sections)}"""
    (OUT / "matches.html").write_text(page("Matches", body))


# ---------- team pages ----------
def last10_table(team):
    rows = []
    for m in team["last_10_matches"]:
        note = f' <small>({escape(m["note"])})</small>' if "note" in m else ""
        rows.append(f"""<tr>
<td class="num">{m['date']}</td>
<td>{escape(m['opponent'])}</td>
<td class="num">{m['home_away']}</td>
<td class="num score">{m['score']}</td>
<td><i class="f {m['result']}">{m['result']}</i>{note}</td>
<td class="comp">{escape(m['competition'])}</td>
</tr>""")
    return f"""<table class="last10">
<thead><tr><th class="num">Date</th><th>Opponent</th><th class="num" title="home or away, from this team's perspective">H/A</th><th class="num" title="goals for-against, from this team's perspective">Score</th><th title="result: W win, D draw (pens count as draws), L loss">Res</th><th>Competition</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""


def stat_strip(s):
    return f"""<dl class="stats">
<div><dt title="wins-draws-losses over the last 10 internationals">Record</dt><dd>{s['record']}</dd></div>
<div><dt title="goals scored per game, last 10">Goals / game</dt><dd>{s['gf_pg']:.1f}</dd></div>
<div><dt title="goals conceded per game, last 10">Conceded / game</dt><dd>{s['ga_pg']:.1f}</dd></div>
<div><dt title="games without conceding, last 10">Clean sheets</dt><dd>{s['cs']}/{s['n']}</dd></div>
<div><dt title="games with 3+ total goals — the standard totals betting line">Over 2.5</dt><dd>{s['o25']}/{s['n']}</dd></div>
<div><dt title="both teams scored — a standard prediction-market category">BTTS</dt><dd>{s['btts']}/{s['n']}</dd></div>
</dl>"""


def build_team_pages():
    for name, t in TEAMS.items():
        g = team_group.get(name, "?")
        fixtures = [m for m in MATCHES if name in (m["home"], m["away"])]
        fx_rows = []
        for m in sorted(fixtures, key=lambda x: x["date_utc"]):
            date_label, time_ = fmt_date(m["date_utc"])
            opp = m["away"] if m["home"] == name else m["home"]
            ha = "H" if m["home"] == name else "A"
            fx_rows.append(
                f'<tr><td class="num">{date_label} {time_}</td><td class="num">{ha}</td>'
                f'<td><a href="../matches/{match_slug(m)}.html">{escape(opp)}</a></td>'
                f'<td class="venue">{escape(m["venue"])}, {escape(m["city"])}</td></tr>'
            )
        host = '<span class="chip">Host nation</span>' if t.get("host") else ""
        body = f"""<div class="teamhead">
<h1>{escape(name)}</h1>
<p class="meta">
<span class="chip">Group {g}</span>
<span class="chip">FIFA #{t['fifa_ranking']}</span>
<span class="chip">{t['confederation']}</span>
{host}
</p>
{form_chips(t, 10)}
</div>
{stat_strip(stats(t))}
<p class="fineprint">Over 2.5 (three-plus total goals) and BTTS (both teams scored) are counted
here because they're the totals categories prediction markets actually trade. Caveat on the
last ten: a few teams padded theirs with friendlies against club or B-team opposition — those
rows say little, and the model's training data excludes non-international opponents entirely.
Matches decided on penalties are recorded as draws (with a note): that's how FIFA counts them
and how the model scores them.</p>
<h2>Last ten internationals</h2>
{last10_table(t)}
<h2>Group {g} fixtures</h2>
<table>
<thead><tr><th class="num">Kick-off (UTC)</th><th class="num">H/A</th><th>Opponent</th><th>Venue</th></tr></thead>
<tbody>{''.join(fx_rows)}</tbody>
</table>"""
        crumb = f'<a href="../index.html">Groups</a> / Group {g} / {escape(name)}'
        (OUT / "teams" / f"{slug(name)}.html").write_text(
            page(name, body, depth=1, crumb=crumb))


# ---------- match pages ----------
def compare_rows(h, a):
    sh, sa = stats(h), stats(a)
    rows = [
        ("FIFA ranking", f"#{h['fifa_ranking']}", f"#{a['fifa_ranking']}"),
        ("Form (last 5)", form_chips(h), form_chips(a)),
        ("Record (10)", sh["record"], sa["record"]),
        ("Goals / game", f"{sh['gf_pg']:.1f}", f"{sa['gf_pg']:.1f}"),
        ("Conceded / game", f"{sh['ga_pg']:.1f}", f"{sa['ga_pg']:.1f}"),
        ("Clean sheets", f"{sh['cs']}/10", f"{sa['cs']}/10"),
        ("Over 2.5 goals", f"{sh['o25']}/10", f"{sa['o25']}/10"),
        ("Both teams scored", f"{sh['btts']}/10", f"{sa['btts']}/10"),
    ]
    tips = {
        "FIFA ranking": "official FIFA ranking, 1 Apr 2026 — not used by the model",
        "Form (last 5)": "most recent first — W win, D draw, L loss",
        "Record (10)": "wins-draws-losses over the last 10 internationals",
        "Clean sheets": "games without conceding, of the last 10",
        "Over 2.5 goals": "games with 3+ total goals, of the last 10",
        "Both teams scored": "games where neither side kept a clean sheet, of the last 10",
    }
    return "".join(
        f'<tr><td class="cl">{l}</td><th title="{tips.get(k, "")}">{k}</th>'
        f'<td class="cr">{r}</td></tr>'
        for k, l, r in rows
    )


def pct(p):
    return f"{p * 100:.0f}¢"


def sim_section(m):
    sim = SIMS.get(str(m["match_id"]))
    if not sim:
        return ""
    ml = sim["moneyline"]
    hf = (f'<p class="meta center">Home-field advantage applied to {escape(sim["home_field"])}.</p>'
          if sim.get("home_field") else
          '<p class="meta center">Neutral venue — no home-field advantage.</p>')
    bar = f"""<div class="mlbar">
<span class="seg home" style="flex:{ml['home']:.4f}"><b>{escape(m['home'])}</b> {pct(ml['home'])}</span>
<span class="seg draw" style="flex:{ml['draw']:.4f}"><b>Draw</b> {pct(ml['draw'])}</span>
<span class="seg away" style="flex:{ml['away']:.4f}"><b>{escape(m['away'])}</b> {pct(ml['away'])}</span>
</div>"""
    t = sim["totals"]
    mkt = PRICES.get(str(m["match_id"]), {}).get("moneyline", {})
    rows = [
        (f"{m['home']} to win", ml["home"], mkt.get("home")),
        ("Draw", ml["draw"], mkt.get("draw")),
        (f"{m['away']} to win", ml["away"], mkt.get("away")),
        ("Over 1.5 goals", t["over_1.5"], None), ("Under 1.5 goals", 1 - t["over_1.5"], None),
        ("Over 2.5 goals", t["over_2.5"], None), ("Under 2.5 goals", 1 - t["over_2.5"], None),
        ("Over 3.5 goals", t["over_3.5"], None), ("Under 3.5 goals", 1 - t["over_3.5"], None),
        ("Both teams score — Yes", sim["btts"], None), ("Both teams score — No", 1 - sim["btts"], None),
        (f"{m['home']} −1.5 (win by 2+)", sim["spread"]["home_-1.5"], None),
        (f"{m['away']} −1.5 (win by 2+)", sim["spread"]["away_-1.5"], None),
    ]
    market_rows = []
    for k, v, price in rows:
        if price is not None:
            edge = (v - price) * 100
            cls = "pos" if edge >= 3 else "neg" if edge <= -3 else ""
            mkt_cell = f'<td class="num">{price * 100:.1f}¢</td>' \
                       f'<td class="num edge {cls}">{edge:+.1f}¢</td>'
        else:
            mkt_cell = '<td class="num dim">—</td><td class="num dim">—</td>'
        market_rows.append(
            f'<tr><td>{escape(k)}</td><td class="num">{v * 100:.1f}%</td>'
            f'<td class="num fair">{pct(v)}</td>{mkt_cell}</tr>')
    market_note = (f'<p class="meta center">Polymarket prices as of {PRICES_AT}. '
                   'Positive edge = model thinks Yes is underpriced.</p>'
                   if mkt else
                   '<p class="meta center">No Polymarket market listed for this fixture yet.</p>')
    scorelines = " · ".join(
        f"<b>{s['score']}</b> <small>{s['p'] * 100:.0f}%</small>" for s in sim["top_scores"])
    bt = f" · backtest log-loss {SIM_LOGLOSS} vs 1.046 baseline on 1,071 matches" if SIM_LOGLOSS else ""
    return f"""<section class="sim">
<h2>Simulation — fair prices vs market</h2>
<p class="fineprint">Fair price is the model's probability written in Polymarket cents — a 56¢
fair price means 56%, and a share bought below it profits on average <em>if the model is right</em>.
Edge = fair minus market: green means the market sells the outcome cheaper than the model values it.
xG here is Dixon-Coles expected goals from attack/defence ratings, not the shot-based xG of
broadcast graphics. Spread −1.5 = win by two or more clear goals.</p>
{hf}
<p class="meta center">Model expected goals: {escape(m['home'])} {sim['xg']['home']} — {sim['xg']['away']} {escape(m['away'])}</p>
{bar}
<table class="markets">
<thead><tr><th>Market</th><th class="num" title="model probability of this outcome">Probability</th><th class="num" title="the model probability written as a share price — buy below this and you profit on average if the model is right">Fair</th><th class="num" title="live Polymarket YES price at last snapshot">Polymarket</th><th class="num" title="fair minus market — positive (green) means the market sells it cheaper than the model values it">Edge</th></tr></thead>
<tbody>{''.join(market_rows)}</tbody>
</table>
{market_note}
<p class="scorelines">Most likely scorelines: {scorelines}</p>
<p class="modelnote">Dixon-Coles weighted Poisson · internationals 2018–2026, tuned
hyperparameters{bt}.
A market priced below fair is value <em>if you trust the model</em>; it knows nothing about
injuries, lineups or motivation.</p>
</section>"""


def build_match_pages():
    for m in MATCHES:
        h, a = TEAMS[m["home"]], TEAMS[m["away"]]
        date_label, time_ = fmt_date(m["date_utc"])
        score = f'<div class="bigscore">{m["score"]}</div>' if m["score"] else ""
        body = f"""<div class="card">
<p class="meta center">Group {m['group']} · Matchday {m['matchday']} · {date_label}, {time_} UTC<br>
{escape(m['venue'])}, {escape(m['city'])}</p>
<div class="versus">
<h1>{team_link(m['home'], 1)}</h1>
<span class="v">v</span>
<h1>{team_link(m['away'], 1)}</h1>
</div>
{score}
<table class="compare">{compare_rows(h, a)}</table>
</div>
{sim_section(m)}
<div class="twocol">
<section><h2>{escape(m['home'])} — last ten</h2>{last10_table(h)}</section>
<section><h2>{escape(m['away'])} — last ten</h2>{last10_table(a)}</section>
</div>"""
        crumb = (f'<a href="../matches.html">Matches</a> / Matchday {m["matchday"]} / '
                 f'{escape(m["home"])} v {escape(m["away"])}')
        (OUT / "matches" / f"{match_slug(m)}.html").write_text(
            page(f"{m['home']} v {m['away']}", body, depth=1, crumb=crumb))


# ---------- futures page ----------
def build_futures():
    if not TOURNEY:
        return
    rows = []
    for name, p in TOURNEY.items():
        if name not in TEAMS:
            continue
        cells = "".join(
            f'<td class="num{" hot" if p[k] >= 0.5 else ""}">{p[k] * 100:.1f}%</td>'
            for k in ("win_group", "r32", "qf", "sf", "final", "champion"))
        rows.append(f'<tr><td>{team_link(name)}</td>'
                    f'<td><b class="gchip">{team_group.get(name, "?")}</b></td>{cells}</tr>')
    body = f"""<h1>Tournament futures</h1>
<p class="standfirst">100,000 Monte Carlo tournaments on a 200-model bootstrap ensemble,
using the official FIFA bracket.</p>
<p class="fineprint">Reach R32 is not the same as win group — eight third-placed teams advance
too, which is why mid-tier teams clear 70% there. Columns nest (champion ⊂ final ⊂ SF…), and
each column sums across all 48 teams to the slots available: 12 group wins, 2 finalists, 1 champion.
Read every percentage as a fair Polymarket price for that future. The ensemble matters: simulating
with 200 bootstrap refits instead of one model widens uncertainty and shaves points off the
favourite — that haircut is honesty, not noise. Anomalies are modelled too, as zero-mean
randomness with assumed magnitudes: a per-tournament form shock (injuries, chemistry) on every
team, knockout attrition (a 10% chance each tie leaves lasting damage — cards, knocks), and a
fatigue penalty after 120-minute matches. None of it favours anyone on average; all of it
favours outsiders, because chaos always does.</p>
<table class="futures">
<thead><tr><th>Team</th><th title="group A-L">Grp</th><th class="num" title="finish top of the group">Win group</th><th class="num" title="advance to the round of 32 — top two per group plus the eight best third-placed teams">Reach R32</th>
<th class="num" title="reach the quarter-finals">QF</th><th class="num" title="reach the semi-finals">SF</th><th class="num" title="reach the final">Final</th><th class="num" title="win the tournament — column sums to 100% across all teams">Champion</th></tr></thead>
<tbody>{''.join(rows)}</tbody>
</table>"""
    (OUT / "futures.html").write_text(page("Futures", body))


# ---------- bracket / predictions page ----------
def build_bracket():
    if not PRED:
        return
    acc = PRED.get("accuracy")
    if acc and acc.get("graded_group_matches"):
        st = "".join(
            f"<div><dt>{k}</dt><dd>{v}</dd></div>" for k, v in (
                ("Matches graded", acc["graded_group_matches"]),
                ("Results called", f"{acc['result_hits']} ({acc['result_pct'] * 100:.0f}%)"),
                ("Exact scores", acc["exact_score_hits"]),
                ("Brier (blend)", acc["brier"]),
            ))
        acc_html = f'<dl class="stats">{st}</dl>'
        if acc.get("compare"):
            comp_rows = "".join(
                f'<tr><td>{src.title()}</td>'
                f'<td class="num">{v["brier"]}</td>'
                f'<td class="num">{v["logloss"]}</td></tr>'
                for src, v in acc["compare"].items())
            acc_html += f"""<table class="ko">
<thead><tr><th>Probability source</th><th class="num" title="mean squared error of the probabilities — lower is better; guessing equally scores 0.667">Brier</th><th class="num" title="penalises confident wrong calls hardest — lower is better; guessing equally scores 1.099">Log-loss</th></tr></thead>
<tbody>{comp_rows}</tbody></table>
<p class="meta center">Lower is better — this settles whether the model, the market,
or the blend prices matches best (market graded on {acc['market_priced_matches']} priced matches).</p>"""
    else:
        acc_html = ('<p class="standfirst">No matches graded yet — run '
                    '<code>wc26_update_results.py</code> then rebuild once games finish.</p>')

    rounds = {}
    for k in PRED["knockout"]:
        rounds.setdefault(k["round"], []).append(k)
    ko_html = ""
    for rname in ("Round of 32", "Round of 16", "Quarter-final",
                  "Semi-final", "Third place", "Final"):
        if rname not in rounds:
            continue
        lines = "".join(
            f'<tr><td class="num">{k["match"]}</td>'
            f'<td>{team_link(k["team1"])} <em>v</em> {team_link(k["team2"])}</td>'
            f'<td class="pick">{escape(k["pick"])}</td>'
            f'<td class="num">{k["p_pick"] * 100:.0f}%</td></tr>'
            for k in rounds[rname])
        ko_html += f"""<section><h2>{rname}</h2>
<table class="ko"><thead><tr><th class="num" title="official FIFA match number">#</th><th>Tie (predicted)</th><th>Pick</th><th class="num" title="the model's own probability for its pick — 50% means a forced coin-flip call">Conf.</th></tr></thead>
<tbody>{lines}</tbody></table></section>"""

    gt_html = ""
    for g in sorted(PRED["group_tables"]):
        rows = "".join(
            f'<tr><td class="num">{i + 1}</td><td>{team_link(r["team"])}</td>'
            f'<td class="num">{r["xpts"]:.1f}</td></tr>'
            for i, r in enumerate(PRED["group_tables"][g]))
        gt_html += f"""<section class="group"><h2><span>Group</span> {g}</h2>
<table><thead><tr><th class="num">#</th><th>Team</th><th class="num">xPts</th></tr></thead>
<tbody>{rows}</tbody></table></section>"""

    rows = []
    for p in sorted(PRED["group_matches"], key=lambda x: x["date_utc"]):
        if "actual_score" in p:
            mark = '<i class="f W">✓</i>' if p["hit"] else '<i class="f L">✗</i>'
            actual = f'<td class="num score">{p["actual_score"]}</td><td>{mark}</td>'
        else:
            actual = '<td class="num dim">—</td><td class="dim">—</td>'
        conf = p["p"][p["pred_result"]] * 100
        rows.append(
            f'<tr><td class="num">{p["date_utc"][:10]}</td>'
            f'<td><b class="gchip">{p["group"]}</b></td>'
            f'<td>{escape(p["home"])} <em>v</em> {escape(p["away"])}</td>'
            f'<td class="num score">{p["pred_score"]}</td>'
            f'<td class="num">{conf:.0f}%</td>{actual}</tr>')
    track_html = f"""<table>
<thead><tr><th class="num">Date</th><th title="group A-L">Grp</th><th>Fixture</th>
<th class="num" title="most likely exact score under the model">Pred</th><th class="num" title="probability of the predicted 1X2 result (market-blended)">Conf.</th><th class="num" title="filled in by wc26_update_results.py as games finish">Actual</th><th></th></tr></thead>
<tbody>{''.join(rows)}</tbody></table>"""

    body = f"""<h1>The predicted tournament</h1>
<p class="standfirst">Every match called in advance — locked {PRED['locked_at']},
graded against reality as results land. Picks are modal outcomes from the mean model;
the official FIFA bracket decides who meets whom.</p>
<div class="champ">Predicted champion: <b>{team_link(PRED['champion'])}</b></div>
<p class="fineprint">A locked bracket never updates — when reality diverges, the picks stay frozen,
because a prediction you can revise isn't a prediction. The Conf column is the model's own
probability for its pick: a 50% pick is a coin flip it was forced to call, so judge the model by
the scorecard's probability metrics, not the ✓/✗ column. Brier and log-loss score the
probabilities themselves (lower is better; guessing ⅓-⅓-⅓ scores 0.667 Brier, 1.099 log-loss) —
and the model/market/blend comparison is the real experiment here: it settles which forecaster
deserves your trust with actual match results.</p>
<h2>Scorecard</h2>
{acc_html}
{ko_html}
<h2>Predicted group tables</h2>
<div class="groups">{gt_html}</div>
<h2>Group-stage match tracker</h2>
{track_html}"""
    (OUT / "bracket.html").write_text(page("Bracket", body))


# ---------- awards page ----------
def fmt_cents(v):
    return f"{v * 100:.1f}¢" if v is not None else "—"


def build_awards():
    if not AWARDS:
        return

    def edge_cell(e):
        if e is None:
            return '<td class="num dim">—</td>'
        cls = "pos" if e >= 0.03 else "neg" if e <= -0.03 else ""
        return f'<td class="num edge {cls}">{e * 100:+.1f}¢</td>'

    boot_rows = "".join(
        f'<tr><td>{escape(b["player"])}</td><td>{team_link(b["team"])}</td>'
        f'<td class="num">{b["intl_goals_24_26"]}</td>'
        f'<td class="num">{b["exp_goals"]:.1f}</td>'
        f'<td class="num fair">{b["p_model"] * 100:.1f}¢</td>'
        f'<td class="num">{fmt_cents(b["market"])}</td>{edge_cell(b["edge"])}</tr>'
        for b in AWARDS["golden_boot"][:20])
    nation_rows = "".join(
        f'<tr><td>{team_link(n["team"])}</td>'
        f'<td class="num">{n["exp_goals"]:.1f}</td>'
        f'<td class="num fair">{n["p_model"] * 100:.1f}¢</td>'
        f'<td class="num">{fmt_cents(n["market"])}</td>{edge_cell(n["edge"])}</tr>'
        for n in AWARDS["top_scorer_nation"][:12])
    glove_rows = "".join(
        f'<tr><td class="num">{i + 1}</td><td>{escape(g["player"])}</td>'
        f'<td>{team_link(g["team"])}</td>'
        f'<td class="num">{g["p_final"] * 100:.1f}%</td>'
        f'<td class="num">{g["conceded_pg"]:.2f}</td>'
        f'<td class="num">{fmt_cents(g.get("market"))}</td></tr>'
        for i, g in enumerate(AWARDS["golden_glove"][:12]))
    ball_rows = "".join(
        f'<tr><td>{escape(b["player"])}</td>'
        f'<td>{team_link(b["team"]) if b["team"] else "—"}</td>'
        f'<td class="num">{fmt_cents(b["market"])}</td>'
        f'<td class="num">{b["team_champion_p"] * 100:.1f}%'
        f'</td></tr>' if b["team_champion_p"] is not None else
        f'<tr><td>{escape(b["player"])}</td><td>—</td>'
        f'<td class="num">{fmt_cents(b["market"])}</td><td class="num dim">—</td></tr>'
        for b in AWARDS["golden_ball"][:12])

    body = f"""<h1>The honours board</h1>
<p class="standfirst">Golden Boot and top-scoring nation are modelled — each player's
goals simulated across the same 100,000 tournaments behind the Futures page, using his
share of his team's international goals since 2024. Glove and Ball are softer ground:
one is a labelled heuristic, the other pure market.</p>

<h2>Golden Boot — modelled</h2>
<p class="fineprint">xG (tourn.) is the player's expected tournament goals: his share of his
team's international goals since 2024, applied to his team's goal count in each simulated
tournament — so deep-run odds are baked in, and a striker on a likely semi-finalist beats an
equal scorer on a group-stage exit. The share is not adjusted for opposition quality, which is
why CONCACAF strikers rate high and the market disagrees. A "—" market means Polymarket simply
hasn't listed the player: the model's co-favourite is unpriced, which is either an oversight
or a verdict.</p>
<table class="ko">
<thead><tr><th>Player</th><th>Team</th><th class="num" title="international goals 2024-26, all competitions — the basis of his share of team goals">Intl goals 24–26</th>
<th class="num" title="expected tournament goals: his share applied to his team's goals across 100k simulated tournaments — deep runs included">xG (tourn.)</th><th class="num" title="probability of winning the Golden Boot, as a fair price">Model</th><th class="num" title="live Polymarket YES price">Polymarket</th><th class="num" title="model minus market — positive means underpriced">Edge</th></tr></thead>
<tbody>{boot_rows}</tbody></table>

<h2>Top scoring nation — modelled</h2>
<table class="ko">
<thead><tr><th>Team</th><th class="num">Exp. goals</th><th class="num">Model</th>
<th class="num">Polymarket</th><th class="num">Edge</th></tr></thead>
<tbody>{nation_rows}</tbody></table>

<h2>Golden Glove — heuristic lean</h2>
<p class="standfirst">Rank = P(reach final) × defensive record. Not a calibrated
probability; the market column is the bettable number.</p>
<table class="ko">
<thead><tr><th class="num" title="heuristic rank: reach-final probability x defensive record — not a calibrated probability">#</th><th>Keeper</th><th>Team</th><th class="num" title="team's probability of reaching the final (Glove winners almost always come from finalists)">P(final)</th>
<th class="num" title="team goals conceded per game, last 10">Conceded/g</th><th class="num" title="live Polymarket YES price">Polymarket</th></tr></thead>
<tbody>{glove_rows}</tbody></table>

<h2>Golden Ball — market only</h2>
<p class="standfirst">Best-player awards are voted, not scored; we show the market
with each candidate's team title odds for context.</p>
<table class="ko">
<thead><tr><th>Player</th><th>Team</th><th class="num">Polymarket</th>
<th class="num">Team champion (model)</th></tr></thead>
<tbody>{ball_rows}</tbody></table>
<p class="modelnote">{escape(AWARDS["method"])} Prices as of {AWARDS["prices_at"]}.</p>"""
    (OUT / "awards.html").write_text(page("Awards", body))


CSS = """/* WC26 Form Book — editorial racing-form aesthetic */
:root {
  --paper: #f6f1e6;
  --paper-2: #efe8d8;
  --ink: #211d16;
  --ink-soft: #6b6353;
  --rule: #cfc4ab;
  --green: #14633f;
  --red: #a72a1e;
  --amber: #9a7b2d;
}
* { box-sizing: border-box; }
body {
  margin: 0;
  background: var(--paper);
  background-image: repeating-linear-gradient(0deg, transparent 0 2px, rgba(33,29,22,.012) 2px 4px);
  color: var(--ink);
  font: 15px/1.5 "IBM Plex Mono", monospace;
}
main { max-width: 1080px; margin: 0 auto; padding: 0 24px 48px; }
h1, h2, .wordmark, .versus h1 { font-family: "Fraunces", serif; }
h1 { font-size: 2.6rem; font-weight: 900; letter-spacing: -.02em; margin: 1.2rem 0 .4rem; }
h2 { font-size: 1.25rem; font-weight: 600; border-bottom: 2px solid var(--ink); padding-bottom: .25rem; margin: 2rem 0 .8rem; }
a { color: var(--green); text-decoration: none; }
a:hover { text-decoration: underline; text-underline-offset: 3px; }

/* masthead */
.masthead {
  text-align: center; padding: 26px 16px 14px;
  border-bottom: 3px double var(--ink); margin-bottom: 8px;
}
.kicker { font-size: .72rem; letter-spacing: .28em; text-transform: uppercase; color: var(--ink-soft); }
.wordmark {
  font-size: clamp(2.4rem, 6vw, 3.6rem); font-weight: 900; color: var(--ink);
  display: inline-block; line-height: 1; margin: 6px 0 10px; letter-spacing: -.03em;
}
.wordmark:hover { text-decoration: none; color: var(--green); }
.masthead nav { font-size: .85rem; text-transform: uppercase; letter-spacing: .18em; }
.masthead nav span { color: var(--rule); margin: 0 10px; }
.crumb { max-width: 1080px; margin: 10px auto 0; padding: 0 24px; font-size: .78rem; color: var(--ink-soft); }
.standfirst { color: var(--ink-soft); margin-top: 0; }

/* tables */
table { width: 100%; border-collapse: collapse; font-size: .85rem; }
th { font-size: .68rem; text-transform: uppercase; letter-spacing: .12em; color: var(--ink-soft); font-weight: 500; text-align: left; }
td, th { padding: .45rem .6rem .45rem 0; border-bottom: 1px solid var(--rule); vertical-align: baseline; }
tbody tr:hover { background: var(--paper-2); }
.num { text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
td.num { color: var(--ink-soft); }
.score { color: var(--ink) !important; font-weight: 600; }
.comp, .venue { color: var(--ink-soft); font-size: .78rem; }

/* form chips */
.form { display: inline-flex; gap: 3px; }
.f {
  font-style: normal; font-weight: 600; font-size: .68rem;
  width: 1.45em; height: 1.45em; display: inline-flex; align-items: center; justify-content: center;
  border-radius: 2px; color: var(--paper);
}
.f.W { background: var(--green); }
.f.L { background: var(--red); }
.f.D { background: var(--amber); }

/* groups grid */
.groups { display: grid; grid-template-columns: repeat(auto-fill, minmax(310px, 1fr)); gap: 28px 36px; margin-top: 24px; }
.group h2 { display: flex; align-items: baseline; gap: .5rem; font-size: 1.6rem; font-weight: 900; border-bottom: 2px solid var(--ink); }
.group h2 span { font-size: .7rem; font-family: "IBM Plex Mono", monospace; font-weight: 500; letter-spacing: .25em; text-transform: uppercase; color: var(--ink-soft); }
.group td:last-child, .group th:last-child { text-align: right; }
.tlink { color: var(--ink); font-weight: 600; }
.tlink:hover { color: var(--green); }
sup.host { color: var(--red); font-size: .62rem; letter-spacing: .08em; }

/* matchday sections */
.matchday h2 { font-size: 1.1rem; }
.fixture a { color: var(--ink); font-weight: 600; }
.fixture a:hover { color: var(--green); }
.fixture em { font-style: italic; color: var(--ink-soft); font-weight: 400; }
.gchip { font-size: .72rem; border: 1px solid var(--ink); padding: 0 .35em; border-radius: 2px; }

/* team page */
.teamhead { text-align: center; padding: 1rem 0 .5rem; }
.teamhead h1 { margin-bottom: .6rem; }
.meta { display: flex; gap: .5rem; justify-content: center; flex-wrap: wrap; margin: .4rem 0 .9rem; }
.meta.center { display: block; text-align: center; color: var(--ink-soft); font-size: .8rem; }
.chip { border: 1px solid var(--ink); border-radius: 999px; padding: .1em .8em; font-size: .72rem; text-transform: uppercase; letter-spacing: .1em; }
.stats { display: flex; flex-wrap: wrap; gap: 0; border: 2px solid var(--ink); margin: 1.4rem 0; }
.stats div { flex: 1 1 110px; padding: .7rem .9rem; border-right: 1px solid var(--rule); text-align: center; }
.stats div:last-child { border-right: 0; }
.stats dt { font-size: .62rem; text-transform: uppercase; letter-spacing: .14em; color: var(--ink-soft); }
.stats dd { margin: .15rem 0 0; font-size: 1.25rem; font-weight: 600; font-family: "Fraunces", serif; }

/* match page */
.card { text-align: center; }
.versus { display: flex; align-items: baseline; justify-content: center; gap: 1.2rem; flex-wrap: wrap; margin: .6rem 0; }
.versus h1 { font-size: clamp(1.6rem, 4.5vw, 2.8rem); margin: 0; }
.versus h1 a { color: var(--ink); }
.versus h1 a:hover { color: var(--green); text-decoration: none; }
.versus .v { font-family: "Fraunces", serif; font-style: italic; color: var(--red); font-size: 1.4rem; }
.bigscore { font-family: "Fraunces", serif; font-size: 3rem; font-weight: 900; }
.compare { max-width: 640px; margin: 1.2rem auto 0; }
.compare th { text-align: center; font-size: .68rem; padding: .5rem; }
.compare .cl { text-align: right; font-weight: 600; width: 38%; }
.compare .cr { text-align: left; font-weight: 600; width: 38%; }
.compare td .form { vertical-align: middle; }
.twocol { display: grid; grid-template-columns: 1fr 1fr; gap: 36px; margin-top: 1rem; }
.twocol .comp { display: none; }
@media (max-width: 860px) { .twocol { grid-template-columns: 1fr; } }

footer { max-width: 1080px; margin: 0 auto; padding: 18px 24px 40px; border-top: 3px double var(--ink); font-size: .72rem; color: var(--ink-soft); }
footer p { margin: .2rem 0; }

/* mobile */
@media (max-width: 700px) {
  main { padding: 0 14px 40px; }
  .crumb { padding: 0 14px; }
  h1 { font-size: 1.9rem; }
  .wordmark { font-size: 2.1rem; }
  .masthead { padding: 18px 8px 10px; }
  .masthead nav { font-size: .7rem; letter-spacing: .08em; }
  .masthead nav span { margin: 0 5px; }
  table { display: block; overflow-x: auto; -webkit-overflow-scrolling: touch; }
  .group table { display: table; }   /* narrow enough to render full-width */
  table { font-size: .78rem; }
  td, th { padding: .4rem .45rem .4rem 0; }
  td.num, th.num { white-space: nowrap; }
  .comp, .venue { white-space: nowrap; }
  .stats div { flex: 1 1 90px; padding: .5rem .4rem; }
  .stats dd { font-size: 1.05rem; }
  .mlbar .seg { font-size: .58rem; padding: .5em .15em; }
  .versus { gap: .6rem; }
  .versus .v { font-size: 1rem; }
  .bigscore { font-size: 2.2rem; }
  .champ { font-size: 1.15rem; padding: .6rem .8rem; }
  .fineprint { font-size: .72rem; }
  .twocol { gap: 20px; }
}

/* simulation section */
.sim { max-width: 640px; margin: 2.5rem auto 0; }
.sim h2 { text-align: center; border-bottom: 2px solid var(--ink); }
.mlbar { display: flex; gap: 2px; margin: 1rem 0 1.2rem; border: 2px solid var(--ink); padding: 2px; }
.mlbar .seg {
  min-width: 0; overflow: hidden; white-space: nowrap; text-align: center;
  font-size: .72rem; padding: .55em .2em; color: var(--paper);
}
.mlbar .seg b { display: block; font-weight: 600; }
.mlbar .home { background: var(--green); }
.mlbar .draw { background: var(--amber); }
.mlbar .away { background: var(--red); }
.markets td.fair { font-weight: 600; }
.markets td.edge.pos { color: var(--green); font-weight: 600; }
.markets td.edge.neg { color: var(--red); font-weight: 600; }
.markets td.dim { color: var(--rule); }
.futures td.hot { color: var(--green); font-weight: 600; }
.champ { text-align: center; font-family: "Fraunces", serif; font-size: 1.5rem;
  border: 3px double var(--ink); padding: .8rem 1rem; margin: 1.2rem auto; max-width: 560px; }
.ko .pick { font-weight: 600; }
.ko em, .standfirst code { font-style: italic; color: var(--ink-soft); }
.scorelines { text-align: center; font-size: .85rem; }
.scorelines small { color: var(--ink-soft); }
.modelnote { font-size: .72rem; color: var(--ink-soft); text-align: center; max-width: 54ch; margin: 1.2rem auto 0; }
[data-tip]:not([data-tip=""]) {
  cursor: help; position: relative;
  text-decoration: underline dotted var(--ink-soft);
  text-underline-offset: 3px;
}
[data-tip]:not([data-tip=""]):hover::after {
  content: attr(data-tip);
  position: absolute; left: 0; top: calc(100% + 4px); z-index: 20;
  background: var(--ink); color: var(--paper);
  font: 400 .72rem/1.45 "IBM Plex Mono", monospace;
  text-transform: none; letter-spacing: 0; text-align: left;
  padding: .5em .75em; border-radius: 2px;
  width: max-content; max-width: 250px; white-space: normal;
  pointer-events: none;
}
th.num[data-tip]:hover::after, dt[data-tip]:hover::after { left: auto; right: 0; }
span.form[data-tip]:hover::after { left: auto; right: 0; }
.fineprint {
  font-size: .76rem; color: var(--ink-soft); line-height: 1.55;
  border-left: 3px solid var(--rule); padding-left: .9rem; margin: .4rem 0 1.4rem;
}
.sim .fineprint { margin-left: auto; margin-right: auto; }
"""

if OUT.exists():
    shutil.rmtree(OUT)
(OUT / "teams").mkdir(parents=True)
(OUT / "matches").mkdir()
(OUT / "style.css").write_text(CSS)
build_index()
build_matches_list()
build_team_pages()
build_match_pages()
build_futures()
build_bracket()
build_awards()
n = sum(1 for _ in OUT.rglob("*.html"))
print(f"built {n} pages in {OUT}")
