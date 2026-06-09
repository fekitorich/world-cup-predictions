# WC26 Simulation — Method Notes

## Methods considered

| Method | Verdict |
|---|---|
| Plain Poisson (Maher 1982) | Too crude — misprices draws and low scores |
| **Dixon-Coles (1997)** | **Chosen.** Industry baseline; attack/defense ratings + low-score correction; fits in seconds |
| Elo→goals hybrids (538 SPI style) | Comparable accuracy, more moving parts, no public Elo feed needed anyway |
| ML (boosting/NN) | Needs player-level features to beat DC; overkill for laptop + group stage |
| LLM-based prediction | Rejected: expensive, unverifiable, no calibrated probabilities |

## Model

- Data: martj42/international_results (49k matches), completed internationals 2018 → present (`international_results.csv`).
- Weighted Poisson MLE per team (attack + defense), fixed-point iteration, pure stdlib Python.
- Time decay: 18-month half-life. Friendlies weighted ×0.6.
- Shrinkage: 8 pseudo-matches toward average (protects thin-data teams: Curaçao, Haiti, NZ).
- Dixon-Coles ρ = −0.10 low-score adjustment on the 13×13 score grid (exact probabilities, no Monte Carlo noise).
- Home advantage (+0.277 log-goals, fitted) applied only when a team plays in its own country (USA/Mexico/Canada fixtures at home venues).

## Validation (held-out)

Fit on data to 2025-06-01, tested on the following 1,071 internationals:
log-loss **0.897** vs 1.046 frequency baseline · Brier 0.528 · accuracy 59.9% vs 48.5% baseline.

## Outputs (Polymarket categories)

Per match (`wc26_simulations.json`, rendered on match pages): moneyline (home/draw/away),
totals O/U 1.5/2.5/3.5, BTTS yes/no, spread ±1.5, top-5 scorelines, expected goals.
Probabilities double as fair prices in ¢ (Polymarket shares settle at $1).

## Known blind spots

No injuries/suspensions/lineups, no motivation effects (dead rubbers on matchday 3),
no weather/altitude, tournament friendlies in form data can be soft (e.g. "Ghana B").
Treat as a fair-value anchor, not an oracle.

## Pipeline

```
python3 wc26_fetch.py        # refresh team last-10 (API-Football)
curl ... international_results.csv   # refresh history (see notes)
python3 wc26_simulate.py     # backtest + 72 simulations
python3 wc26_build_site.py   # regenerate site
```

---

## Upgrade pass (2026-06-09, evening)

**Hyperparameter tuning** (coordinate descent, held-out 2025-06→2026-06):
half-life 548→**1000d**, friendlies ×0.6→**×0.8**, shrinkage 8→**4**, ρ −0.10→**−0.05**.
Log-loss **0.897 → 0.854**. Longer memory + lighter shrinkage won: international teams
are more stable than club sides. Caveat: tuned on a single 1,071-match window.

**Tournament Monte Carlo** (`wc26_tournament.py`, 20k sims): exact group schedule,
sampled from DC grids; top-2 + 8 best thirds; R32 draw & bracket approximated
(randomized per sim, no same-group R32 ties); KO draws split proportionally (ET/pens);
host advantage in KO: USA all rounds, MEX/CAN through R16. Favourites: ARG 20.8%,
ESP 10.5%, BRA 9.4%, ENG 6.8%, JPN 6.1%. **France 3.9% diverges hard from market
(~10%)** — soft recent form + Group I (Senegal, Norway); treat as model blind spot
or value case, investigate before staking futures.

**Polymarket integration** (`wc26_polymarket.py`, free Gamma API): moneyline-only at
match level (3 binary markets per event). Slug `fifwc-{code}-{code}-{local-date}`;
question text uses "Türkiye"/"Côte d'Ivoire"/"Czechia" (alias map in script).
64/72 fixtures priced; missing 8 not listed yet. Match pages show fair vs market
with edge column (±3¢ highlight). First snapshot: market overprices Mexico v RSA
home win by ~7¢ vs model.

## Ensemble upgrade (2026-06-09, late)

`wc26_tournament.py` rewritten (numpy in `.venv/`):
- **200-model Bayesian bootstrap** (exponential re-weighting) — sims draw from
  parameter uncertainty; Argentina champion 20.8% → 19.2% (honest shrink).
- **Official FIFA bracket** from Wikipedia: R32 template matches 73–88 with
  third-place slot group constraints (backtracking allocation), real flow to final.
- **100k sims** for futures; deterministic mean-model bracket **locked** in
  `wc26_predictions.json` (all 72 group matches w/ modal scores + KO picks to the
  final). Predicted: Argentina over Spain in the final, Brazil third.
- `wc26_update_results.py` grades the locked file as results land (1X2 hit rate,
  exact scores, Brier, per-stage overlap); site "Bracket" page shows the scorecard.

## Accuracy package (2026-06-09, night)

1. **Multi-window tuning** (4 rolling 12-month windows, 4,228 test matches):
   picked the *same* params as the single window — they generalize. Honest CV
   log-loss is **0.891** (the oft-quoted 0.854 was the easiest window).
2. **Margin capping: rejected by the data.** cap=4 and cap=3 both lost to
   no-cap on CV log-loss. Blowout information apparently is information.
3. **Market blend** (log-opinion pool, w=0.35 on normalized Polymarket prices):
   group-match picks/probs now blended where priced (64/72). Flipped 7
   near-coin-flip picks toward the market. Locked file stores p_model /
   p_market / p (blend); `wc26_update_results.py` grades all three so the
   tournament itself will settle which source prices best.
4. **Run archive**: every output JSON is copied to `runs/<stamp>_<name>.json`;
   site footer shows model-run and price-snapshot timestamps.
