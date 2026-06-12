# Betting executor

Turns the model's edges into capped, Kelly-sized Polymarket orders.
**This stakes real money when run with `--live`. Read this file first.**

## One command

```
.venv/bin/python3 betting/run.py            # refresh -> scan -> plan -> DRY RUN
.venv/bin/python3 betting/run.py --live     # same, then places REAL orders
```

`run.py` chains the whole flow (Polymarket snapshot refresh, scan of every
category enabled in config, plan build, execution) and refuses to start on
stale inputs: model outputs older than `max_sims_age_hours`, an exhausted
total cap, a missing key, or — for `--live` — a missing `config.local.json`
(real money never runs on the committed placeholder caps). `--limit N`,
`--skip-refresh`, `--allow-stale` are passed through / available.

## Step-by-step flow (what run.py does)

```
1. edit betting/config.local.json    # YOUR caps + category gates (gitignored)
2. python3 pipeline/wc26_polymarket.py   # refresh snapshot (late-listed books)
3. python3 betting/find_bets.py      # plan from RAW model vs live prices (no keys)
4. review betting/state/plan.json    # every bet, stake, edge — read it
5. .venv/bin/python3 betting/place_bets.py          # dry run, prints orders
6. .venv/bin/python3 betting/place_bets.py --live   # real money
```

## Safety rails (enforced in place_bets.py, not just the plan)

- total across all runs ≤ `max_total_stake_usdc` (persistent ledger in `state/`)
- every stake ≤ `max_per_bet_usdc`
- a market already in the ledger is never bought twice — token-level AND
  market-level (holding one side blocks ever buying the other side)
- combined exposure per fixture (and per team for futures) capped at
  `max_per_match_usdc`: five correlated bets on one match are one big bet
- dry run is the default; `--live` is an explicit opt-in
- a plan older than `max_plan_age_min` is refused outright — prices and
  kickoffs have moved; rebuild it (override: `--ignore-plan-age`)
- kickoff is re-checked at execution time: a started match is never bet,
  even from a plan built before kickoff
- the plan is sized against the bankroll that *remains* (cap minus ledger),
  and both sides of one market can't appear in the same batch
- execution-time price check, both directions: refused if the live ask rose
  past `max_slippage_cents` (edge gone) **or** fell past
  `max_price_drop_cents` (a collapse means the market knows something the
  pre-match plan doesn't — re-scan, don't "buy the dip")
- wallet USDC balance is checked before the first live order
- `python3 betting/paper.py` — paper-trading scoreboard (CLV + resolved
  PnL per category for every candidate ever scanned, no money involved)
- only positive-edge buys (either side of a binary); Golden Ball/Glove never bet (no calibrated model)
- every non-moneyline category (exact score, totals, team totals, BTTS, spread,
  halves, first-to-score, futures, corners) ships **off** in the committed config —
  a test enforces it; enable per category in your gitignored `config.local.json`
- started matches are never scanned; illiquid/placeholder books are rejected
  (`min_liquidity_usdc`, `max_book_spread`)

## Secrets — never committed

`betting/.env` (gitignored, as is all of `betting/state/`):

```
POLYMARKET_PRIVATE_KEY=0x...    # export: Polymarket settings (email login)
                                #         or MetaMask account details
POLYMARKET_FUNDER=0x...         # your Polymarket profile/deposit address
POLYMARKET_SIGNATURE_TYPE=1     # 1 = email/Google login, 2 = MetaMask login
```

An existing funded Polymarket account is all you need — the script trades
as that account. If you've ever placed a trade in the UI, allowances are
already set. (`.venv/bin/pip install py-clob-client-v2` once.)

## Honest caveats

- Plan prices are Gamma mid-prices; market orders fill against the book, so
  expect a little slippage on thin markets. Edges under ~5¢ may not survive it.
- The model knows nothing about injuries/lineups. The Boot model's shares are
  opposition-unadjusted (it loves CONCACAF strikers). Bet sizes assume the
  model is right *on average* — quarter-Kelly exists because it isn't always.
- Polymarket prices are probabilities; a "win" pays $1/share. Sized stakes are
  in USDC spent, not shares.
