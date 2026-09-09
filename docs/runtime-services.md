# Runtime service ownership

Run `jrc run` (or `./run up`) in a foreground terminal. Use `jrc run --qa` for read-only voice QA; it prints its mode and sets `VOICE_QA_MODE=1` for children. `jrc status` reports the running mode, readiness and ownership. Press Ctrl-C or run `jrc down` to stop the matching supervisor and clean its owned resources.

Supabase, Ollama, Kokoro, the OrbStack VM/Kubernetes node, and deployed UI and LiveKit resources are shared prerequisites. The supervisor borrows them only after identity and health checks; it never starts or stops them. Missing prerequisites cause an explicit failure.

The supervisor may own foreground Whisper, the UI and signaling port forwards, the tracked loopback LiveKit bridge, a room-mode agent, and—in QA mode—the guarded proxy. Existing processes must match the expected executable and arguments. Cleanup checks PID, process group, session and OS start identity; unfamiliar listeners refuse startup. Tailscale mappings are removed only if the supervisor created them and their targets still match. Cleanup never resets Serve or enables Funnel.

Normal mode launches `.venv-agent/bin/python agent/main.py start` with QA mode unset or zero. An existing exact `dev` or `start` worker can be borrowed only after verification. Console mode never serves `/mic`. QA mode selects a QA room worker and passes its selected receipt to the guarded proxy; it never starts the normal worker path.

Both modes verify the published verifier hash on each invocation and pass explicit `--require-mode normal|qa`. Readiness requires live process identity, matching mode and server, automatic room registration, a sole automatic-worker pool, and current load below its declared threshold. QA additionally verifies read-only evidence. A cached READY marker or an old QA receipt cannot establish normal readiness. Unavailable load and unknown thresholds fail closed.

Normal and QA use separate receipt files. For borrowed workers the defaults are `docs.local/voice-normal-agent-receipt.json` and `docs.local/voice-qa-agent-receipt.json`; overrides are `AGENT_NORMAL_RECEIPT_FILE` and `VOICE_QA_RECEIPT_FILE`. Equal resolved paths refuse startup. Owned workers use separate per-run receipts and logs. Database credentials are captured into child environment only, never supervisor state or output.

The deployed `/mic` page must already exist. Desktop QA uses the loopback proxy. `VOICE_QA_PHONE=1 jrc run --qa` enables an owned tailnet HTTPS mapping and reports its URL; the same read-only guards apply. Startup rolls back owned resources if a later readiness check fails. The phone, media path and installed command need their own live verification; source tests do not establish those claims.

Whisper uses `VOICE_STT_MODEL` (default `~/.cache/whisper/ggml-small.bin`), `VOICE_STT_PORT` (default `8912`), and `VOICE_STT_LANGUAGE` (default `en`). The selected port is forwarded to the room agent as `STT_URL`. Other agent configuration is inherited from the invoking environment.

Owned normal and QA agents retain diagnostics in `.run-logs/<UTC>-<service>-<unique-id>/` beside `.run-state`. Startup prints the exact directory. `agent.log` contains the agent's own log; `console.log` captures stdout/stderr, including startup tracebacks; `events.jsonl` records lifecycle events and the exit code when this supervisor observed it. A separate cleanup process cannot recover an OS exit code and records no inferred value. Receipt snapshots are historical evidence, never current readiness.

Ctrl-C, `jrc down`, startup rollback and later runs preserve these directories. They are private (directory mode 700, files 600), git-ignored, and may contain conversation text; do not publish them. Remove old `.run-logs` directories explicitly after retaining the diagnostics you need. Runtime cleanup still removes owned processes and temporary readiness state.
