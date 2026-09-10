#!/bin/bash
set -euo pipefail
umask 077
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${repo_root}"
: "${JRC_LOCAL_ANALYSIS_ENV_FILE:?set to an op run env template path}"
analysis_python="${JRC_LOCAL_ANALYSIS_PYTHON:-python3}"
exec "${analysis_python}" -m scripts.local_analysis_supervisor
