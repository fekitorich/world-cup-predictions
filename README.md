# The Form Book — World Cup 2026

Personal research tool for the FIFA World Cup 2026: a Dixon-Coles goal model,
100,000-tournament Monte Carlo simulations over a bootstrap ensemble,
live Polymarket price comparison, player-award models, and a locked
pre-tournament bracket graded publicly as results land.

**Site:** http://amirdaraee.com/world-cup-predictions/

## Pages

- **Groups** — all 48 teams, official FIFA rankings, last-5 form
- **Matches** — 72 group fixtures; every match card prices moneyline, totals,
  BTTS and spread, with model-vs-Polymarket edge highlighting
- **Futures** — championship/stage odds from 100k simulated tournaments
  (200-model bootstrap ensemble, official FIFA bracket, anomaly modeling:
  form shocks, knockout attrition, extra-time fatigue)
- **Awards** — modelled Golden Boot & top-scoring nation; market-priced
  Golden Ball & Glove
- **Bracket** — every match predicted through the final, locked 2026-06-09,
  with a public scorecard grading model vs market vs blend on real results
- **Method** — how all of it is computed, validation numbers, known blind spots
- **Versions** — immutable daily snapshots of the whole site, so past
  predictions never disappear

## Method, briefly

Weighted-Poisson attack/defence ratings (Dixon-Coles) fit on 8,081
internationals since 2018 (from a 49k-match dataset that we audited and
patched against the primary source), hyperparameters chosen by 4-window
rolling cross-validation (CV log-loss 0.891 vs 1.046 baseline). Group-match
probabilities blend the model with Polymarket prices (log-opinion pool,
w=0.35); raw model is kept separate for edge-finding. Full write-up:
[the Method page](http://amirdaraee.com/world-cup-predictions/method.html)
and [wc26_model_notes.md](wc26_model_notes.md).

## Betting executor

`betting/` turns model-vs-market edges into capped, fractional-Kelly
Polymarket orders (dry-run by default, hard per-bet and total caps, a
persistent ledger against double-betting). All personal data — keys, caps,
ledger — stays in gitignored local files. See [betting/README.md](betting/README.md).

## Reproduce

Needs an [API-Football](https://www.api-football.com) key in
`.api_football_key` (or `API_FOOTBALL_KEY` env var) and `numpy` in `.venv/`
for the tournament engine. Pipeline order is documented in
[CLAUDE.md](CLAUDE.md). Matchday routine:

```
python3 wc26_update_results.py        # pull results, grade the locked bracket
python3 wc26_polymarket.py            # fresh market prices
python3 wc26_simulate.py              # refit on latest data
.venv/bin/python3 wc26_tournament.py  # re-run 100k tournaments
.venv/bin/python3 wc26_awards.py      # award odds
python3 wc26_build_site.py snapshot   # rebuild site + freeze a dated snapshot
git add -A && git commit && git push  # deploy
```

*Not betting advice; the model knows nothing about injuries or lineups.*
