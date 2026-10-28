#!/bin/sh
# Portable equivalent of docs.local/tools/run-suite-capped.sh for CI.
set -u
suite=${1:?suite required}; cap=${2:-3072}; limit=${3:-600}
state=$(mktemp -d) || exit 1
interrupted=0
trap 'interrupted=1' INT TERM
node "$(dirname "$0")/cap-runner.mjs" "$suite" "$state/pid" & supervisor=$!
# Node creates the group without a TTY; dash disables `set -m` without one.
while [ ! -s "$state/pid" ]; do
  if ! kill -0 "$supervisor" 2>/dev/null; then
    wait "$supervisor"; rc=$?
    rmdir "$state"
    exit "$rc"
  fi
  sleep 1
done
root=$(cat "$state/pid")
rm "$state/pid"
rmdir "$state"
tree() { for c in $(pgrep -P "$1" 2>/dev/null); do tree "$c"; done; echo "$1"; }
stop() {
  # Leave the runner's children alive so its finally block can use Docker/Supabase.
  # 90s covers the 1.5s abort drain, restart protection, data backup/stop and scan.
  # Ignore further signals while this bounded cleanup is in progress.
  trap '' INT TERM
  kill -TERM "$root" 2>/dev/null || :
  grace=0
  while kill -0 "$root" 2>/dev/null && [ "$grace" -lt 90 ]; do
    sleep 1
    grace=$((grace + 1))
  done
  # Reparented descendants (and children they spawn) retain this owned group.
  # Use /bin/kill: dash's builtin does not accept the -- separator.
  /bin/kill -TERM -- "-$root" 2>/dev/null || :
  sleep 2
  /bin/kill -KILL -- "-$root" 2>/dev/null || :
  wait "$supervisor" 2>/dev/null || :
}
trap 'stop; exit 130' INT TERM
if [ "$interrupted" -eq 1 ]; then stop; exit 130; fi
start=$(date +%s); peak=0
while kill -0 "$root" 2>/dev/null; do
  pids=$(tree "$root"); rss=0
  for p in $pids; do r=$(ps -o rss= -p "$p" 2>/dev/null || :); rss=$((rss + ${r:-0})); done
  mb=$((rss/1024)); now=$(date +%s)
  [ "$mb" -le "$peak" ] || peak=$mb
  if [ "$mb" -gt "$cap" ] || [ "$((now-start))" -gt "$limit" ]; then
    echo "CAP-KILL suite=$suite rss=${mb}MB cap=${cap}MB elapsed=$((now-start))s"
    # Names/RSS only: arguments could contain local auth tokens or credentials.
    for p in $pids; do ps -o pid=,ppid=,rss=,comm= -p "$p" 2>/dev/null || :; done
    stop
    exit 137
  fi
  sleep 2
done
wait "$supervisor"; rc=$?
echo "suite=$suite exit=$rc peak_rss=${peak}MB elapsed=$(($(date +%s)-start))s"
exit "$rc"
