# The Form Book — World Cup 2026

Personal research tool for the FIFA World Cup 2026: a Dixon-Coles goal model,
Monte Carlo tournament simulations, Polymarket price comparison, and a locked
pre-tournament bracket graded against reality as results land.

**Site:** http://amirdaraee.com/world-cup-predictions/

## What's inside

- **Groups / team dossiers** — all 48 teams, FIFA rankings, last-10 form
- **Match cards** — head-to-head stats, model fair prices vs live Polymarket
  prices with edge highlighting
- **Futures** — 100k tournament simulations over a 200-model bootstrap
  ensemble, official FIFA bracket
- **Bracket** — every match predicted to the final, locked 2026-06-09,
  with a public accuracy scorecard (model vs market vs blend)

## Method, briefly

Weighted-Poisson attack/defence ratings (Dixon-Coles) fit on all
internationals since 2018, hyperparameters tuned on four rolling validation
windows (CV log-loss 0.891 vs 1.046 baseline). Group-match probabilities are
blended with Polymarket prices (log-opinion pool, w=0.35). Full notes in
[wc26_model_notes.md](wc26_model_notes.md).

## Betting executor

`betting/` turns model-vs-market edges into capped, fractional-Kelly
Polymarket orders (dry-run by default, hard per-bet and total caps, a
persistent ledger against double-betting). All personal data — keys, caps,
ledger — stays in gitignored local files. See [betting/README.md](betting/README.md).

## Reproduce

Needs an [API-Football](https://www.api-football.com) key in
`.api_football_key` (or `API_FOOTBALL_KEY` env var) and `numpy` in `.venv/`
for the tournament engine. Pipeline order is documented in
[CLAUDE.md](CLAUDE.md).

*Not betting advice; the model knows nothing about injuries or lineups.*
