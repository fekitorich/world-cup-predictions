#!/bin/zsh
# Nightly matchday update: results -> grading -> prices -> refit -> sims ->
# awards -> site + snapshot -> push.  NO betting steps - bets stay manual.
# Secrets: scripts read .api_football_key locally (chmod 600, gitignored);
# nothing secret enters logs, commits, or this file.
set -e
cd "$(dirname "$0")"
LOG="logs/matchday-$(date -u +%Y%m%d-%H%M).log"
mkdir -p logs
exec >> "$LOG" 2>&1
echo "=== matchday run $(date -u '+%Y-%m-%d %H:%M UTC') ==="

git checkout main -q
git pull -q --ff-only

# test gate: red tests = no publish, failure stays in this log
python3 -m unittest discover -s tests -q || { echo "TESTS FAILED - aborting publish"; exit 1; }

python3 wc26_update_results.py          # results, grading, scorers, KO fixtures
python3 wc26_polymarket.py              # fresh market prices (also new KO/late markets)
python3 wc26_espn_ids.py                # live-link ids (picks up KO fixtures)
python3 wc26_simulate.py                # refit on latest results
.venv/bin/python3 wc26_tournament.py    # 100k tournament sims (lock untouched)
.venv/bin/python3 wc26_awards.py        # boot/awards odds
python3 wc26_build_site.py snapshot     # rebuild + freeze today's archive copy

if [[ -n "$(git status --porcelain -- . ':!experiments')" ]]; then
  git add -A -- ':!experiments'
  git commit -q -m "Matchday update $(date -u +%Y-%m-%d)"
  git push -q
  echo "pushed matchday update"
else
  echo "no changes to publish"
fi
echo "=== done $(date -u '+%H:%M UTC') ==="
