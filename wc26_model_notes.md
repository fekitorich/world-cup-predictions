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

## Anomaly model (2026-06-10)

Tournament sims (`wc26_tournament.py`) now include zero-mean anomaly variance:
- **Form shock**: per-tournament per-team N(0, 0.06) on log scoring rates —
  injuries/chemistry/camp variance the goals data can't see.
- **KO attrition**: each knockout tie, 10% chance per team of a lasting
  −0.04 log-attack knock (suspensions, injuries); **ET fatigue**: −0.03
  next match after going 120 minutes.
- Magnitudes are stated assumptions, not estimates. All shocks are zero-mean:
  nobody is helped on average, but favourites lose tail mass to the field —
  Argentina champion 19.0% → 16.6%, which moves the model toward market consensus.
- Implementation switched tournament sampling to vectorised plain Poisson
  (DC rho kept for match-card pricing only; ~1% draw-rate effect in sims).
- Locked bracket unaffected (deterministic mean-model path; shocks are zero-mean).

## Squad-value prior (2026-06-10, pre-matchday-1) — the Nate Silver borrow

Ratings now get `att += B*z/2, def -= B*z/2` where z = standardized log squad
market value (Transfermarkt, all 211→top-100 teams, minnow default €8m).
- **Validation** (fit to 2025-06, test on following 1,071 matches): log-loss
  0.854 → **0.818** at the B=0.4 optimum, clean peak (worse by 1.0). Shipped
  B=0.35 as a look-ahead haircut (current values partly reflect past results).
  Single biggest upgrade in the project; reaches ~market-grade calibration.
- **Caveats**: single-window validation (historical values unavailable);
  values are a 2026-06 snapshot, refresh wc26_squad_values.json occasionally.
- **Effect**: France champion 4.0→8.2% (was the documented blind spot),
  Spain 9.0→14.1, England 6.1→10.5; Japan 6.0→2.9, Colombia 5.0→2.9.
  Remaining model-vs-market gaps are now defensible disagreements, not
  blindness. Locked bracket unchanged (it testifies for the old model).
- Files: wc26_squad_values.json (data), wc26_value_test.py (falsification
  harness — rerun after value refreshes).

## Exact-score grid calibration (2026-06-11, matchday 1) — a clean negative

Polymarket listed per-match exact-score books (sibling events,
`{slug}-exact-score`, 17 cells: 0-0..3-3 + other), so the score grid is now
a bettable surface, not just bracket decoration. Audit before betting it:
- **New harness**: `wc26_simulate.py gridtest` — 17-class log-loss +
  per-cell observed/predicted on the holdout; `tuneboost` fits a `min2_boost`
  multiplier on cells where both sides score 2+ (the region DC's tau
  doesn't reach), trained on the 2022-25 windows.
- **Holdout (1,071 matches, 2025-06→2026-06)**: 17-class log-loss 2.4247.
  Tuned rho=-0.05 leaves its four target cells essentially perfect
  (0-0/1-0/0-1/1-1 obs/pred 0.98-1.02). The min2 region looked 28% hot
  (2-2 obs/pred 1.42) — **but it doesn't replicate**: training windows give
  ratios 0.93/1.16/0.93, and the fitted boost is exactly 1.0 (likelihood
  degrades monotonically above it). The holdout blip was a ~2σ window fluke.
- **Conclusion**: the DC grid is already calibrated for exact scores; no
  correction shipped (`min2_boost` stays 1.0 in params, plumbing kept in
  score_grid/grid_np for re-checks as tournament data accrues).
- **Betting**: `exact_scores` (17 cells) now emitted per match in
  wc26_simulations.json; wc26_polymarket.py snapshots the books
  (64/64 listed fixtures on day 1); find_bets.py scans them behind
  `include.exact_score` — **ships OFF**. Cell edges are the model's
  thinnest-evidence claims and mostly re-express the 1X2 opinion; the
  moneyline is usually the better instrument for the same view. Started
  matches are never scanned (pre-match model vs in-play prices).

## Market expansion pass (2026-06-12, pre-matchday-2)

Six new model surfaces, each priced from machinery that already existed or
from one validated parameter — plus a second clean negative.
- **Team totals & extra O/U lines (0.5/4.5/5.5)**: grid marginals and sums —
  zero new assumptions, emitted per match.
- **First to score**: Poisson race argument, P(home first)=λ1/(λ1+λ2)·(1−P(0-0)).
  Spot check vs market (USA-PAR): model 59/31/10 vs prices 56/34/10.
- **Half markets**: `half_split=0.447` — share of goals before HT, fit on
  2,360 goals across six tournaments (per-tournament 0.37-0.46, WC22 lowest
  at 0.399; `pipeline/wc26_half_split.py` refits). A half is a shorter DC
  match: scale λs, reuse the grid. Spot check (USA-PAR HT): model 39/45/17
  vs prices 34/46/19.
- **Futures scanning**: group winners + reach-R32/R16/QF/SF/final/champion
  books vs the 100k-sim ensemble (no new model; the scanner just never
  looked). Both sides of every binary are scanned.
- **Corners (negative result #2)**: 250-fixture backfill (WC22, AFCON23,
  Asian23, Euro24, Copa24; `wc26_corners.py`). NegBin total-corners with an
  xG slope **lost** leave-one-tournament-out to intercept-only (NLL 2.7050
  vs 2.6888) — attacking quality does not transfer to corner counts across
  tournaments. Shipped intercept-only (μ=9.18, k≈21): a base-rate anchor
  against lazy thin books, nothing more.
- **Skipped deliberately**: per-match scorer/shots/assists props — Polymarket
  lists shots-on-target only, books carry ~$4 liquidity, and our shares are
  opposition-unadjusted. No model beats no market.
All new categories ship OFF in betting config; both-sides scanning with the
liquidity/spread filter and pre-kickoff guard apply everywhere.
