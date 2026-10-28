#!/bin/sh
# Portable equivalent of docs.local/tools/run-suite-capped.sh for CI.
set -u
suite=${1:?suite required}; cap=${2:-3072}; limit=${3:-600}
node "$suite" & root=$!
tree() { for c in $(pgrep -P "$1" 2>/dev/null); do tree "$c"; done; echo "$1"; }
stop() {
  # Leave the runner's children alive so its finally block can use Docker/Supabase.
  # 90s covers the 1.5s abort drain, restart protection, data backup/stop and scan.
  # Ignore further signals while this bounded cleanup is in progress.
  trap '' INT TERM
  remaining=$(tree "$root")
  kill -TERM "$root" 2>/dev/null || :
  grace=0
  while kill -0 "$root" 2>/dev/null && [ "$grace" -lt 90 ]; do
    for p in $(tree "$root"); do
      case " $remaining " in *" $p "*) ;; *) remaining="$remaining $p" ;; esac
    done
    sleep 1
    grace=$((grace + 1))
  done
  # Include cleanup subprocesses created during the grace; retain orphaned PIDs.
  remaining="$remaining $(tree "$root")"
  for p in $remaining; do kill -TERM "$p" 2>/dev/null || :; done
  sleep 2
  for p in $remaining; do kill -KILL "$p" 2>/dev/null || :; done
  wait "$root" 2>/dev/null || :
}
trap 'stop; exit 130' INT TERM
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
wait "$root"; rc=$?
echo "suite=$suite exit=$rc peak_rss=${peak}MB elapsed=$(($(date +%s)-start))s"
exit "$rc"
