#!/bin/bash
set -euo pipefail
repo_root="$(cd "$(dirname "$0")/.." && pwd)"
python3 "$repo_root/scripts/analysis_codex_preflight.py" "$@"
exec python3 "$repo_root/docs.local/tools/local-analysis-tool.py" install "$@"
