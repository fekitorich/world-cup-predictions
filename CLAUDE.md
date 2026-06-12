# World Cup Predictions

Personal research tool for betting on FIFA World Cup 2026 (Polymarket). Static site
("The Form Book", https://wcformbook.com) generated from JSON data + a Dixon-Coles
simulation model.

## Layout

- `pipeline/` — all model/site scripts (run from repo root: `python3 pipeline/...`)
- `data/` — every JSON/CSV/NPZ input and canonical model output
- `docs/` — generated site, GitHub Pages root, never edit by hand
  (report.html = accuracy report, regraded nightly; archive/ = immutable snapshots)
- `betting/` — Polymarket executor (own README)
- `tests/` — gate suite; `runs/` — time-coded archives of every result write
- `wc26_matchday.sh` — launchd entry point (06:30/23:30); stays at repo root,
  the plist points at it by absolute path

## Pipeline (order matters)

```
python3 pipeline/wc26_fetch.py        # refresh each team's last-10 matches (API-Football)
curl -sL https://raw.githubusercontent.com/martj42/international_results/master/results.csv \
     -o data/international_results.csv     # refresh match history for the model
python3 pipeline/wc26_simulate.py     # fit model, backtest, write data/wc26_simulations.json
python3 pipeline/wc26_corners.py predict    # corner O/U from the base-rate NegBin (after simulate)
python3 pipeline/wc26_half_split.py   # (occasional) refit half_split from API-Football HT scores
python3 pipeline/wc26_corners.py backfill && python3 pipeline/wc26_corners.py fit
                                      # (occasional) corners history + LOTO validation
python3 pipeline/wc26_simulate.py tune      # (occasional) re-tune hyperparams -> data/wc26_params.json
python3 pipeline/wc26_simulate.py gridtest  # exact-score calibration audit (17-cell log-loss)
python3 pipeline/wc26_simulate.py tuneboost # (occasional) refit min2_boost on training windows
.venv/bin/python3 pipeline/wc26_tournament.py  # 200-model ensemble + 100k sims (needs numpy venv)
                                      # -> data/wc26_tournament.json (futures) + wc26_predictions.json
                                      #    (locked bracket; --force to re-lock, normally never)
python3 pipeline/wc26_polymarket.py   # Polymarket prices incl. exact-score books (free, no key)
python3 pipeline/wc26_players.py      # squads + player intl goals + award market prices (~300 API calls)
python3 pipeline/wc26_player_pages.py # (occasional) candidate dossiers for /players pages (~140 calls)
python3 pipeline/wc26_espn_ids.py     # (once) ESPN gameId mapping for live links
.venv/bin/python3 pipeline/wc26_awards.py   # Golden Boot model etc (after tournament.py)
python3 pipeline/wc26_update_results.py     # during tournament: pull actual results, grade predictions
python3 pipeline/wc26_build_site.py   # regenerate docs/ live pages
python3 pipeline/wc26_charts.py       # (occasional) regenerate method-page SVG charts
python3 -m unittest discover -s tests # gate: matchday script runs this before publishing
python3 pipeline/wc26_build_site.py snapshot  # ...plus freeze docs/archive/<date>/ (once per matchday)
python3 -m http.server 8742 --directory docs  # browse
```

## Data files (`data/`)

- `fifa_world_cup_2026.json` — 48 teams: confederation, FIFA ranking, last 10 matches
- `fifa_world_cup_2026_group_matches.json` — 72 group fixtures (match_id = API-Football fixture id)
- `wc26_params.json` — tuned model hyperparameters (incl. min2_boost, kept honest at 1.0)
- `wc26_simulations.json` — per-match probabilities (moneyline/totals 0.5-5.5/BTTS/spread/
  top scores + `exact_scores` 17-cell book + `team_totals` + `first_to_score` +
  `halftime`/`second_half` 1X2 via the fitted half_split)
- `wc26_corners.json` + `wc26_corners_model.json` + `wc26_corners_history.json` —
  total-corners NegBin (intercept-only: the xG slope failed LOTO validation)
- `wc26_tournament.json` — per-team futures probabilities (win group → champion)
- `wc26_market_prices.json` — Polymarket snapshots: moneylines + exact-score books
  + totals/BTTS/spread (from the per-match `-more-markets` sibling event;
  re-fetch near kickoff; late-listed fixtures get picked up on re-run)
- `wc26_squad_values.json` — Transfermarkt squad values (refresh occasionally;
  pipeline/wc26_value_test.py revalidates beta)
- `wc26_predictions.json` — LOCKED bracket (see Conventions)
- `wc26_model_notes.md` (repo root) — method R&D, validation numbers, known blind spots

## Betting module (`betting/`)

- `find_bets.py` (plan from RAW-model edges vs live prices, Kelly-sized) →
  review `betting/state/plan.json` → `place_bets.py` (dry-run default,
  `--live` to execute, `--limit N` for partial batches). Uses the
  py-clob-client-v2 SDK (Polymarket migrated exchanges 2026-04-28).
- Categories are gated in config `include`; everything except `moneyline`
  and the two awards ships OFF in the committed config (a test enforces it:
  exact_score, totals, team_totals, btts, spread, halftime, second_half,
  first_to_score, futures, corners) — enable only via config.local.json. Started matches are never scanned
  (pre-match model vs in-play prices), and illiquid/placeholder books are
  rejected (`min_liquidity_usdc` / `max_book_spread` — untraded lines sit
  at ~50/50 and fake a fat edge).
- ALL personal betting data is gitignored and must stay that way:
  `betting/.env` (wallet key + API creds), `betting/config.local.json`
  (real caps), `betting/state/` (plans + ledger). The committed
  `betting/config.json` holds only generic placeholder caps.
- The ledger enforces the total cap across runs and prevents double-betting;
  never edit it by hand.

## Conventions

- Team names are normalized to the main JSON's spelling ("United States", "Turkey",
  "DR Congo", "South Korea"); API-Football and the history CSV use variants — alias
  maps exist in the scripts.
- Data sources: API-Football (Pro plan; key read from env API_FOOTBALL_KEY or the
  gitignored `.api_football_key` file at repo root) for fixtures/results;
  martj42/international_results for model training. Prefer free APIs; ask user for
  keys when needed.
- Mostly stdlib Python; numpy lives only in `.venv/` and only `wc26_tournament.py`
  needs it. Everything else must stay stdlib.
- `data/wc26_predictions.json` is LOCKED (pre-tournament bracket picks for accuracy
  grading). Only `wc26_update_results.py` may write to it (fills actuals);
  never regenerate it without the user explicitly asking (--force).
- Every result-writing script also archives a time-coded copy in `runs/`
  (via `save_versioned` in wc26_simulate.py). The site always shows the
  canonical "latest" files; run timestamps appear in the site footer.
- Group-match picks/probabilities are model×market blends (w=0.35 on
  Polymarket, log-opinion pool) where priced; `p_model`/`p_market` are kept
  alongside so the scorecard can grade model vs market vs blend separately.
