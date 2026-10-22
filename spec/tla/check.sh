#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
tlc=$(command -v "${TLC:-tlc}")
command -v rg >/dev/null
run_dir=$(mktemp -d "${TMPDIR:-/tmp}/jrc-tlc.XXXXXX")
trap 'rm -rf "$run_dir"' EXIT
cp JrcPipeline.tla "$run_dir/"
# Supply an empty/new directory to retain complete logs, configs, and raw traces.
if [[ -n ${TLC_LOG_DIR:-} ]]; then
  mkdir "$TLC_LOG_DIR"
  run_dir_logs=$(cd "$TLC_LOG_DIR" && pwd)
else
  run_dir_logs=$run_dir
fi
run() {
  local name=$1 expected=$2 rc=0
  [[ $run_dir_logs == "$run_dir" ]] || cp "$run_dir/$name.cfg" "$run_dir_logs/"
  (cd "$run_dir" && "$tlc" -workers 1 -fp 0 -seed 1 -difftrace -metadir "$run_dir/$name.states" \
    -config "$name.cfg" JrcPipeline.tla) >"$run_dir_logs/$name.log" 2>&1 || rc=$?
  if [[ $expected == pass ]]; then
    [[ $rc == 0 ]] && rg -q 'Model checking completed. No error has been found.' "$run_dir_logs/$name.log" || {
      cat "$run_dir_logs/$name.log"; return 1;
    }
  else
    [[ $rc == 12 ]] && rg -q "^Error: Invariant $expected is violated\\.$" "$run_dir_logs/$name.log" || {
      cat "$run_dir_logs/$name.log"; return 1;
    }
  fi
  printf '%s: expected %s\n' "$name" "$expected"
  rg 'states generated|depth of the complete' "$run_dir_logs/$name.log"
}
cp JrcPipeline.cfg "$run_dir/target.cfg"
run target pass
for invariant in NoSilentSourceLoss OneVisibleVacancy AliveImpliesFreshCheck DeadlinePassedImpliesClosed LocationAcceptsCityOnly; do
  cp JrcPipeline_current.cfg "$run_dir/$invariant.cfg"
  printf '\nINVARIANT %s\n' "$invariant" >>"$run_dir/$invariant.cfg"
  case $invariant in
    NoSilentSourceLoss) printf 'CONSTRAINT StaleWitness\n' >>"$run_dir/$invariant.cfg" ;;
    OneVisibleVacancy) printf 'CONSTRAINT DistinctWitness\n' >>"$run_dir/$invariant.cfg" ;;
  esac
  run "$invariant" "$invariant"
done
# Metrics already surface all-filtered loss; equal-title/location R1/R1 also groups.
for entry in 'NoSilentSourceLoss GeoWitness pass' 'OneVisibleVacancy RequisitionWitness pass' \
  'OneVisibleVacancy RoleWitness pass' 'OneVisibleVacancy TitleWitness OneVisibleVacancy' \
  'OneVisibleVacancy LocationWitness OneVisibleVacancy' 'OneVisibleVacancy JdWitness OneVisibleVacancy'; do
  read -r invariant witness expected <<<"$entry"
  cp JrcPipeline_current.cfg "$run_dir/$witness.cfg"
  printf '\nINVARIANT %s\nCONSTRAINT %s\n' "$invariant" "$witness" >>"$run_dir/$witness.cfg"
  run "$witness" "$expected"
done
printf 'PASS: target invariants hold; current-code violations and passing controls match.\n'
