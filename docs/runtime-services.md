# Runtime service ownership

Run `jrc run` in a foreground terminal. Use `jrc run --qa` for read-only voice QA; it prints its mode and sets `VOICE_QA_MODE=1` for children. `jrc status` reports the running mode, readiness and ownership. Press Ctrl-C to stop the voice stack. `jrc down` is crash cleanup only; a new `jrc run` also recovers the prior run’s verified resources before starting.

Supabase, Ollama, OrbStack/Kubernetes, the deployed UI and its loopback forward on port 3410 remain always-on prerequisites. Missing prerequisites cause an explicit failure. The supervisor never stops them or removes the dashboard HTTPS mapping on port 8445.

The supervisor adopts or starts the approved preinstalled Kokoro container and LiveKit Deployment. Ctrl-C stops that exact Kokoro instance and scales that exact LiveKit Deployment to zero. It does not delete the container, Deployment, Service, ConfigMaps or Secrets. Replaced identities or changed deployment specs refuse cleanup and retain a diagnostic record. Kokoro health uses a ten-second budget; repeated post-start readiness failures report degradation without tearing down unrelated services.

Whisper, the signaling forward, tracked loopback bridge and room agent are foreground processes started when absent. Existing verified processes remain borrowed; unfamiliar listeners refuse startup. Cleanup checks PID, process group, session and OS start identity. The voice mappings on ports 8446 and 7881 are adopted for the run and removed only while their targets still match. Cleanup never resets Serve or enables Funnel. QA adds the guarded proxy and its optional separate phone mapping.

Normal mode launches `.venv-agent/bin/python agent/main.py start` with QA mode unset or zero. An existing exact `dev` or `start` worker can be borrowed only after verification. Console mode never serves `/mic`. QA mode selects a QA room worker and passes its selected receipt to the guarded proxy; it never starts the normal worker path.

Both modes verify the published verifier hash on each invocation and pass explicit `--require-mode normal|qa`. Readiness requires live process identity, matching mode and server, automatic room registration, a sole automatic-worker pool, and current load below its declared threshold. QA additionally verifies read-only evidence. A cached READY marker or an old QA receipt cannot establish normal readiness. Unavailable load and unknown thresholds fail closed.

Normal and QA use separate receipt files. For borrowed workers the defaults are `docs.local/voice-normal-agent-receipt.json` and `docs.local/voice-qa-agent-receipt.json`; overrides are `AGENT_NORMAL_RECEIPT_FILE` and `VOICE_QA_RECEIPT_FILE`. Equal resolved paths refuse startup. Owned workers use separate per-run receipts and logs. Database credentials are captured into child environment only, never supervisor state or output.

The deployed `/mic` page must already exist. Desktop QA uses the loopback proxy. `VOICE_QA_PHONE=1 jrc run --qa` enables an owned tailnet HTTPS mapping and reports its URL; the same read-only guards apply. Startup rolls back owned resources if a later readiness check fails. The phone, media path and installed command need their own live verification; source tests do not establish those claims.

Whisper uses `VOICE_STT_MODEL` (default `~/.cache/whisper/ggml-small.bin`), `VOICE_STT_PORT` (default `8912`), and `VOICE_STT_LANGUAGE` (default `en`). The selected port is forwarded to the room agent as `STT_URL`. Other agent configuration is inherited from the invoking environment.

Owned normal and QA agents retain diagnostics in `.run-logs/<UTC>-<service>-<unique-id>/` beside `.run-state`. Startup prints the exact directory. `agent.log` contains the agent's own log; `console.log` captures stdout/stderr, including startup tracebacks; `events.jsonl` records lifecycle events and the exit code when this supervisor observed it. A separate cleanup process cannot recover an OS exit code and records no inferred value. Receipt snapshots are historical evidence, never current readiness.

Ctrl-C, `jrc down`, startup rollback and later runs preserve these directories. They are private (directory mode 700, files 600), git-ignored, and may contain conversation text; do not publish them. Remove old `.run-logs` directories explicitly after retaining the diagnostics you need. Runtime cleanup still removes owned processes and temporary readiness state.
