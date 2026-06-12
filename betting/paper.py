"""Grade the paper-trading log: CLV and resolved PnL, no money involved.

  python3 betting/paper.py

For every candidate find_bets.py ever logged (betting/state/paper.json),
takes the FIRST sighting as the paper entry price, then asks Polymarket
what happened since:
  - CLV (closing-line-value proxy): current/last price minus entry price.
    Positive = the market moved toward the model's view after we flagged
    the edge. A model that finds real edge shows positive average CLV
    long before results prove anything.
  - Resolved PnL: for markets that have settled, profit of a flat $1
    stake at the entry price (win: 1/price - 1, lose: -1).
Both reported per category. This is the honest out-of-sample scoreboard
for the edge-finder itself — the ledger only sees what was actually
staked.
"""
import json
import os
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
PAPER = f"{HERE}/state/paper.json"


def gamma_markets(tokens):
    out = {}
    for i in range(0, len(tokens), 20):
        chunk = tokens[i:i + 20]
        # repeated params, not comma-joined: Gamma started rejecting
        # comma lists with 422 "invalid clob token ids" (seen 2026-06-12)
        url = ("https://gamma-api.polymarket.com/markets?"
               + "&".join("clob_token_ids=" + urllib.parse.quote(t)
                          for t in chunk))
        req = urllib.request.Request(url, headers={"User-Agent": "wc26-research"})
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                for m in json.load(r):
                    for j, tok in enumerate(json.loads(m["clobTokenIds"])):
                        out[tok] = (m, j)
        except Exception as e:
            print(f"  gamma chunk failed: {e}")
    return out


def first_seen(runs):
    """token -> first sighting of each candidate (the paper entry price)."""
    first = {}
    for run in runs:
        for c in run["candidates"]:
            if c["token_id"] not in first:
                first[c["token_id"]] = {**c, "at": run["at"]}
    return first


def aggregate(first, markets):
    """Per-category CLV + resolved flat-$1 PnL (pure: no network)."""
    cats = {}
    for tok, c in first.items():
        hit = markets.get(tok)
        if not hit:
            continue
        m, idx = hit
        try:
            cur = float(json.loads(m["outcomePrices"])[idx])
        except (KeyError, ValueError, IndexError):
            continue
        st = cats.setdefault(c["category"], {
            "n": 0, "entry": 0.0, "clv": 0.0,
            "resolved": 0, "wins": 0, "pnl": 0.0})
        st["n"] += 1
        st["entry"] += c["market_p"]
        st["clv"] += cur - c["market_p"]
        if m.get("closed"):
            won = cur > 0.5    # settled prices pin to ~1/~0
            st["resolved"] += 1
            st["wins"] += won
            st["pnl"] += (1 / c["market_p"] - 1) if won else -1.0
    return cats


def main():
    try:
        paper = json.load(open(PAPER))
    except FileNotFoundError:
        print("no paper log yet — run betting/find_bets.py first")
        return
    first = first_seen(paper["runs"])
    print(f"{len(first)} unique paper positions across "
          f"{len(paper['runs'])} scans")
    markets = gamma_markets(list(first))
    cats = aggregate(first, markets)

    print(f"\n{'category':<16}{'n':>4}{'avg entry':>11}{'avg CLV':>9}"
          f"{'resolved':>9}{'wins':>6}{'PnL/$1':>9}")
    tot = {"n": 0, "clv": 0.0, "resolved": 0, "wins": 0, "pnl": 0.0}
    for cat, st in sorted(cats.items()):
        print(f"{cat:<16}{st['n']:>4}{st['entry']/st['n']:>10.2f}¢"
              f"{100*st['clv']/st['n']:>+8.1f}¢{st['resolved']:>9}"
              f"{st['wins']:>6}{st['pnl']:>+9.2f}")
        for k in tot:
            tot[k] += st.get(k, 0)
    if tot["n"]:
        print(f"{'TOTAL':<16}{tot['n']:>4}{'':>11}"
              f"{100*tot['clv']/tot['n']:>+8.1f}¢{tot['resolved']:>9}"
              f"{tot['wins']:>6}{tot['pnl']:>+9.2f}")
    print("\npositive avg CLV = the market keeps moving toward the model's "
          "view after we flag an edge — the early tell that the edge is real.")


if __name__ == "__main__":
    main()
