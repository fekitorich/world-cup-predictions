# The Form Book — World Cup 2026

Personal research tool for the FIFA World Cup 2026: a Dixon-Coles goal model,
100,000-tournament Monte Carlo simulations over a bootstrap ensemble,
live Polymarket price comparison, player-award models, and a locked
pre-tournament bracket graded publicly as results land.

**Site:** https://wcformbook.com

## Pages

- **Groups** — all 48 teams, official FIFA rankings, last-5 form
- **Matches** — 72 group fixtures; every match card prices moneyline, totals,
  BTTS, spread and exact scorelines, with model-vs-Polymarket edge highlighting
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
rolling cross-validation (CV log-loss 0.891 vs 1.046 baseline), plus a
**squad-value prior** (Transfermarkt market values, β fitted out-of-sample —
held-out log-loss 0.854 → 0.818, the project's largest single upgrade).
The exact-score grid is calibration-audited against Polymarket's 17-cell
books (`pipeline/wc26_simulate.py gridtest`).
Group-match probabilities blend the model with Polymarket prices
(log-opinion pool, w=0.35); raw model is kept separate for edge-finding. Full write-up:
[the Method page](https://wcformbook.com/method.html)
and [wc26_model_notes.md](wc26_model_notes.md).

## Repo layout

```
pipeline/          model + site scripts (run from repo root)
data/              all inputs and canonical model outputs (JSON/CSV/NPZ)
docs/              generated site (GitHub Pages root) + immutable archive/
betting/           Polymarket executor — see betting/README.md
tests/             offline gate suite (75 tests; CI + matchday gate)
runs/              time-coded archive of every result write
charts/            method-page SVG sources
wc26_matchday.sh   nightly automation entry point (launchd)
```

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
python3 pipeline/wc26_update_results.py        # pull results, grade the locked bracket
python3 pipeline/wc26_polymarket.py            # fresh market prices + exact-score books
python3 pipeline/wc26_simulate.py              # refit on latest data
.venv/bin/python3 pipeline/wc26_tournament.py  # re-run 100k tournaments
.venv/bin/python3 pipeline/wc26_awards.py      # award odds
python3 pipeline/wc26_build_site.py snapshot   # rebuild site + freeze a dated snapshot
git add -A && git commit && git push           # deploy
```

*Not betting advice; the model knows nothing about injuries or lineups.*
