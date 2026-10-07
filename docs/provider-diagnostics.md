# Provider request diagnostics

Extraction and scoring batch logs include one `event=provider_request` receipt per
`run_brain` invocation: provider, allowlisted model/effort, category, numeric exit
code, UTC start timestamp, monotonic elapsed milliseconds, timeout budget, and stderr truncation flag.
Projection failures before a provider invocation do not emit a request receipt.
Library callers emit nothing unless they enable `provider_diagnostic_scope`.

Codex stderr is drained concurrently with stdin. At most the final 16 KiB is retained in
memory; older bytes are discarded, and raw bytes never enter logs or receipts.
Terminal `ERROR:` markers are heuristically classified as auth, quota, or model
access; unknown errors or lost terminal lines yield nonzero_exit. These labels are diagnostic
hints, not grounds for automatic retries or policy changes. Timeout, launch,
unsupported runtime, configuration, response, and success are separate categories.
Full prompts, schema, profile, credentials, argv, paths, HTTP bodies and exception
messages are excluded. Unrecognized model strings appear as `configured`.
Request results, isolation, model policy and process-group cleanup remain intact.

`scripts/install-local-analysis.sh` runs a read-only preflight before the existing
operator-local wheel installer. It prints the target source pin, selected binary
version and newest executable release in `~/.codex/packages/standalone/releases`.
The comparison is explicitly local; it does not claim the newest published build.
An older pin warns loudly; missing/nonexecutable/wrong-version pins fail before
installation. An unavailable inventory warns that freshness is unknown. Nothing
is auto-upgraded. Copy the preflight to `docs.local/tools/analysis-codex-preflight.py`
and add `python3 "$(dirname "$0")/analysis-codex-preflight.py" "$@"` before the local
wrapper's existing installer exec. Keep these operator-local files out of Git.
