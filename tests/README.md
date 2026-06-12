# Test suite

Four layers, all offline (no network, no keys, no orders). The matchday
gate runs everything; layers exist so a failure tells you *what kind* of
thing broke.

```
tests/
  unit/          pure logic: model math, parsers, betting guards, grading,
                 NegBin corners math, paper-scoreboard aggregation
  integration/   components + real repo state: data-file contracts
                 (fixtures <-> sims <-> snapshot <-> tournament <-> awards),
                 the Dixon-Coles fit on a synthetic league, numpy-vs-stdlib
                 grid parity, merged betting config + ledger invariants
  e2e/           whole flows: the full site built into a temp dir and
                 checked page by page; the entire betting chain (every
                 scanner -> plan -> execution filter) against a faked
                 Gamma API with deliberate traps (started match, dead book)
  smoke/         the repo as checked out is runnable: every script
                 compiles, every data JSON parses, committed configs keep
                 their safety contracts, matchday automation never bets
                 or spends API money
```

## Commands

```bash
python3 -m unittest discover -s tests              # everything (the gate)
python3 -m unittest discover -s tests/unit -t .    # one layer
python3 -m unittest tests.e2e.test_betting_chain   # one module

# branch coverage (coverage.py lives in .venv; numpy tests activate there)
.venv/bin/python3 -m coverage run -m unittest discover -s tests
.venv/bin/python3 -m coverage report
```

## Conventions

- Machine-specific tests (the gitignored ledger, frozen LLM sources) skip
  cleanly where the files don't exist — the suite must pass on a fresh
  clone with no keys.
- Tests never write inside the repo: site builds go to a temp dir, the
  betting e2e fabricates its own data dir.
- Network/CLI-only scripts (fetch, players, charts, espn_ids, half_split,
  value_test, awards) are smoke-compiled only; their logic is either
  trivially I/O or validated by the data contracts their outputs must pass.
- The committed-config tests in smoke/ are load-bearing: they are what
  keeps every risky betting category OFF for anyone who clones this repo.
