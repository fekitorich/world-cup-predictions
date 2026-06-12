"""Render the news-gate log as a local HTML page — the betting UI.

  python3 betting/news_report.py        # writes betting/state/news_report.html
  open betting/state/news_report.html

Strictly local: the page is written inside the gitignored state/ dir and
must never be published — it shows real positions and stakes. news_check.py
regenerates it automatically after every run.
"""
import html
import json
import os
import time

HERE = os.path.dirname(os.path.abspath(__file__))
STATE = f"{HERE}/state"
OUT = f"{STATE}/news_report.html"

CSS = """
body{font:15px/1.55 -apple-system,system-ui,sans-serif;background:#0e1116;
     color:#dbe2ea;max-width:1060px;margin:0 auto;padding:24px}
h1{font-size:22px} h2{font-size:17px;margin-top:34px;border-bottom:1px solid #2a3340;
   padding-bottom:6px} .dim{color:#8b97a5;font-size:13px}
table{border-collapse:collapse;width:100%;margin:10px 0;font-size:14px}
th,td{text-align:left;padding:6px 10px;border-bottom:1px solid #1d242e;vertical-align:top}
th{color:#8b97a5;font-weight:600;font-size:12px;text-transform:uppercase}
.flag{display:inline-block;padding:1px 8px;border-radius:9px;font-size:12px;font-weight:700}
.veto{background:#3d1118;color:#ff7a8a}.caution{background:#3a2c0d;color:#ffc94d}
.clear,.hold{background:#10301c;color:#5ad18a}.review,.sell_flag{background:#3a2c0d;color:#ffc94d}
.reasons{color:#aeb9c6;font-size:13px} .num{font-variant-numeric:tabular-nums}
.kept{color:#5ad18a}.gone{color:#ff7a8a}
.summary{background:#141a22;border:1px solid #222b37;border-radius:8px;
         padding:10px 14px;margin:8px 0;font-size:14px}
"""


def esc(s):
    return html.escape(str(s if s is not None else ""))


def flag_chip(flag):
    return f'<span class="flag {esc(flag)}">{esc(flag).upper()}</span>'


def bets_table(bets, note=""):
    if not bets:
        return f"<p class='dim'>none{note}</p>"
    rows = "".join(
        f"<tr><td>{esc(b.get('bet'))}</td>"
        f"<td class='num'>${b.get('stake_usdc', 0):.2f}</td>"
        f"<td class='num'>{b.get('model_p', 0):.2f}</td>"
        f"<td class='num'>{b.get('market_p', b.get('price_seen', 0)):.2f}</td>"
        f"<td>{esc(b.get('category', ''))}</td>"
        f"<td class='reasons'>{esc('; '.join(b.get('news_reasons', [])))}</td></tr>"
        for b in bets)
    return ("<table><tr><th>bet</th><th>stake</th><th>model</th>"
            "<th>market</th><th>category</th><th>news</th></tr>"
            f"{rows}</table>")


def report_section(rep):
    r = rep.get("report") or {}
    out = [f"<div class='summary'><b>{esc(rep.get('fixture'))}</b> — "
           f"{esc(r.get('summary', ''))}"]
    flags = [f for f in r.get("flags", []) if f.get("flag")]
    for f in flags:
        out.append(f"<br>{flag_chip(f['flag'])} {esc(f.get('bet'))}"
                   f"<div class='reasons'>"
                   f"{esc('; '.join(f.get('reasons') or []))}</div>")
    for ab in r.get("key_absences", []):
        out.append(f"<div class='reasons'>absence: {esc(ab.get('player'))} "
                   f"({esc(ab.get('team'))}, {esc(ab.get('status'))})</div>")
    for adv in rep.get("advisories", []):
        out.append(
            f"<div class='reasons'>advisory: without {esc(adv['player'])} "
            f"({adv['goal_share']:.0%} of {esc(adv['team'])} goals) "
            f"moneyline {esc(adv['moneyline_before'])} → "
            f"{esc(adv['moneyline_adjusted'])} [not applied]</div>")
    out.append("</div>")
    return "".join(out)


def render(log, plan, ledger):
    """Pure: log/plan/ledger dicts in, full HTML page out."""
    runs = (log or {}).get("runs", [])
    latest_plan = next((r for r in reversed(runs) if r["mode"] == "plan"), None)
    latest_hold = next((r for r in reversed(runs) if r["mode"] == "holdings"),
                       None)
    spent = sum(b["stake_usdc"] for b in (ledger or {"placed": []})["placed"])

    parts = [f"<!doctype html><meta charset='utf-8'>"
             f"<title>News gate — local betting report</title>"
             f"<style>{CSS}</style>"
             f"<h1>News gate report <span class='dim'>local only — "
             f"never published</span></h1>"
             f"<p class='dim'>generated {time.strftime('%Y-%m-%d %H:%M UTC', time.gmtime())}"
             f" · ledger ${spent:.2f} placed · {len(runs)} gate run(s) logged</p>"]

    if latest_plan:
        ap = latest_plan.get("applied", {})
        kept = (plan or {}).get("bets", [])
        parts.append(
            f"<h2>Latest plan gate <span class='dim'>{esc(latest_plan['at'])}"
            f" · {esc(latest_plan['model'])}</span></h2>"
            f"<p><span class='kept'>{len(kept)} kept</span> · "
            f"<span class='gone'>{len(ap.get('dropped', []))} removed</span> · "
            f"{len(ap.get('scaled', []))} reduced"
            + (f" · <b class='gone'>{ap['analyst_failures']} dossier(s) "
               f"unchecked (analyst failed)</b>"
               if ap.get("analyst_failures") else "") + "</p>")
        parts.append("<h2>Surviving plan (what --live would place)</h2>")
        parts.append(bets_table(kept))
        gone = set(ap.get("dropped", []))
        parts.append("<h2>Analyst reports</h2>")
        for rep in latest_plan.get("reports", []):
            parts.append(report_section(rep))
        if gone:
            parts.append("<h2>Removed bets</h2><table><tr><th>bet</th></tr>"
                         + "".join(f"<tr><td class='gone'>{esc(b)}</td></tr>"
                                   for b in sorted(gone)) + "</table>")
    else:
        parts.append("<p>No plan-mode run logged yet — run "
                     "<code>betting/news_check.py</code>.</p>")

    if latest_hold:
        flagged = latest_hold.get("applied", {}).get("flagged", [])
        parts.append(
            f"<h2>Latest holdings review <span class='dim'>"
            f"{esc(latest_hold['at'])}</span></h2>")
        if flagged:
            parts.append("<table><tr><th>flag</th><th>position</th>"
                         "<th>why</th></tr>" + "".join(
                             f"<tr><td>{flag_chip(f[0])}</td>"
                             f"<td>{esc(f[1])}</td>"
                             f"<td class='reasons'>{esc('; '.join(f[2]))}</td></tr>"
                             for f in flagged) + "</table>")
        else:
            parts.append("<p class='dim'>no positions flagged</p>")
        for rep in latest_hold.get("reports", []):
            parts.append(report_section(rep))

    parts.append("<p class='dim'>Flags are facts-in, flags-out: the analyst "
                 "can only block or shrink bets, never add or raise one. "
                 "Raw log: betting/state/news_checks.json</p>")
    return "".join(parts)


def load(path):
    try:
        return json.load(open(path))
    except FileNotFoundError:
        return None


def main():
    page = render(load(f"{STATE}/news_checks.json"),
                  load(f"{STATE}/plan.json"),
                  load(f"{STATE}/ledger.json"))
    os.makedirs(STATE, exist_ok=True)
    open(OUT, "w").write(page)
    print(f"report written: {OUT}")


if __name__ == "__main__":
    main()
