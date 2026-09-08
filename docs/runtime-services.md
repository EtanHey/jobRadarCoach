# Runtime service ownership

`./run` loads the ordered adapters from `scripts.runtime_services.build_services`.

Supabase, Ollama, Kokoro, the OrbStack VM/Kubernetes node, and the deployed UI and LiveKit resources are shared prerequisites. The supervisor reports them as borrowed when their exact health and identity checks pass. It never starts or stops them.

The supervisor may own foreground Whisper, the UI `kubectl port-forward`, the tracked loopback LiveKit bridge, and the console agent. Process cleanup is guarded by PID, process group, session ID, and operating-system start identity. Existing listeners must match the expected executable and exact arguments; unfamiliar listeners cause startup to fail.

The Tailscale adapter preserves existing matching mappings and records only mappings it creates. Cleanup re-reads each target and removes it only while it still matches the recorded target. It never resets Tailscale Serve or enables Funnel.

QA mode currently fails before starting any service with `room-mode agent receipt and owned QA proxy are not installed`. A later voice integration slice must supply the room-mode registration receipt, read-only database evidence, proxy, and token attestation; console mode can never satisfy that gate. In normal mode, a newly owned console agent must emit a fresh `starting worker` marker. The agent receives `DATABASE_URL` from captured `supabase status` output; the value is kept in child environment only and is never written to supervisor state or output.

Whisper uses `VOICE_STT_MODEL` (default `~/.cache/whisper/ggml-small.bin`), `VOICE_STT_PORT` (default `8912`), and `VOICE_STT_LANGUAGE` (default `en`). Other agent configuration is inherited from the invoking environment. Missing shared prerequisites or required configuration fail explicitly.
