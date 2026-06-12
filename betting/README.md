# Betting executor

Turns the model's edges into capped, Kelly-sized Polymarket orders.
**This stakes real money when run with `--live`. Read this file first.**

## Flow

```
1. edit betting/config.json          # YOUR caps: total + per-bet + min edges
2. python3 betting/find_bets.py      # plan from RAW model vs live prices (no keys)
3. review betting/state/plan.json    # every bet, stake, edge — read it
4. .venv/bin/python3 betting/place_bets.py          # dry run, prints orders
5. .venv/bin/python3 betting/place_bets.py --live   # real money
```

## Safety rails (enforced in place_bets.py, not just the plan)

- total across all runs ≤ `max_total_stake_usdc` (persistent ledger in `state/`)
- every stake ≤ `max_per_bet_usdc`
- a market already in the ledger is never bought twice
- dry run is the default; `--live` is an explicit opt-in
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
