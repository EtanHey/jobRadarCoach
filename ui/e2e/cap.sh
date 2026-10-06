#!/bin/sh
# Portable equivalent of docs.local/tools/run-suite-capped.sh for CI.
set -u
suite=${1:?suite required}; cap=${2:-3072}; limit=${3:-600}
node "$suite" & root=$!
tree() { for c in $(pgrep -P "$1" 2>/dev/null); do tree "$c"; done; echo "$1"; }
stop() { pids=$(tree "$root"); for p in $pids; do kill "$p" 2>/dev/null || :; done; }
trap 'stop; exit 130' INT TERM
start=$(date +%s); peak=0
while kill -0 "$root" 2>/dev/null; do
  pids=$(tree "$root"); rss=0
  for p in $pids; do r=$(ps -o rss= -p "$p" 2>/dev/null || :); rss=$((rss + ${r:-0})); done
  mb=$((rss/1024)); now=$(date +%s)
  [ "$mb" -le "$peak" ] || peak=$mb
  if [ "$mb" -gt "$cap" ] || [ "$((now-start))" -gt "$limit" ]; then
    echo "CAP-KILL suite=$suite rss=${mb}MB cap=${cap}MB elapsed=$((now-start))s"
    stop; sleep 2
    for p in $pids; do kill -9 "$p" 2>/dev/null || :; done
    exit 137
  fi
  sleep 2
done
wait "$root"; rc=$?
echo "suite=$suite exit=$rc peak_rss=${peak}MB elapsed=$(($(date +%s)-start))s"
exit "$rc"
