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

retry() {  # retry <attempts> <sleep_s> <cmd...>
  local n=$1 s=$2 i; shift 2
  for i in $(seq 1 $n); do
    "$@" && return 0
    echo "attempt $i/$n failed: $*"
    [[ $i -lt $n ]] && sleep $s
  done
  return 1
}

# launchd can fire before Wi-Fi is back up (the 2026-06-12 04:30 run died
# on DNS at git pull): wait up to 5 minutes for the network, then abort
retry 10 30 curl -sI --max-time 10 https://api.github.com >/dev/null || {
  echo "NETWORK DOWN after 5 min - aborting run"; exit 1; }

git checkout main -q
retry 3 20 git pull -q --ff-only

# test gate: red tests = no publish, failure stays in this log
python3 -m unittest discover -s tests -q || { echo "TESTS FAILED - aborting publish"; exit 1; }

python3 pipeline/wc26_update_results.py          # results, grading, scorers, KO fixtures
python3 pipeline/wc26_polymarket.py              # fresh market prices (also new KO/late markets)
python3 pipeline/wc26_espn_ids.py                # live-link ids (picks up KO fixtures)
python3 pipeline/wc26_simulate.py                # refit on latest results
python3 pipeline/wc26_corners.py predict         # corner O/U from base-rate NegBin
.venv/bin/python3 pipeline/wc26_tournament.py    # 100k tournament sims (lock untouched)
.venv/bin/python3 pipeline/wc26_awards.py        # boot/awards odds
python3 pipeline/wc26_build_site.py snapshot     # rebuild + freeze today's archive copy

if [[ -n "$(git status --porcelain -- . ':!experiments')" ]]; then
  git add -A -- ':!experiments'
  git commit -q -m "Matchday update $(date -u +%Y-%m-%d)"
  # a failed push must not lose the run: the commit stays local and the
  # next run's ff-only pull + push carries it out
  if retry 3 30 git push -q; then
    echo "pushed matchday update"
  else
    echo "PUSH FAILED - committed locally, next run publishes"
  fi
else
  echo "no changes to publish"
fi
echo "=== done $(date -u '+%H:%M UTC') ==="
