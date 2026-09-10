#!/bin/bash
set -euo pipefail
umask 077
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"
: "${JRC_LOCAL_ANALYSIS_ENV_FILE:?set to an op run env template path}"
state_dir="${JRC_LOCAL_ANALYSIS_STATE_DIR:-${HOME}/Library/Application Support/jobRadarCoach/local-analysis}"
op_cli="${JRC_ONEPASSWORD_CLI:-op}"
analysis_python="${JRC_LOCAL_ANALYSIS_PYTHON:-python3}"
mkdir -p "${state_dir}/logs"
log_file="${state_dir}/logs/$(date -u '+%Y-%m-%d').jsonl"
diagnostic_log="${state_dir}/logs/$(date -u '+%Y-%m-%d').stderr.log"
"${op_cli}" run --env-file "${JRC_LOCAL_ANALYSIS_ENV_FILE}" -- \
  "${analysis_python}" -m scripts.local_analysis \
    --max-items "${JRC_LOCAL_ANALYSIS_MAX_ITEMS:-6}" \
    --timeout-seconds "${JRC_LOCAL_ANALYSIS_TIMEOUT_SECONDS:-120}" \
    --lease-seconds "${JRC_LOCAL_ANALYSIS_LEASE_SECONDS:-900}" \
    --lock-file "${state_dir}/worker.lock" >>"${log_file}" 2>>"${diagnostic_log}"
