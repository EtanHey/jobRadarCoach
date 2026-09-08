# Voice QA URL defaults

`scripts.runtime_qa_config.resolve_qa_urls(context)` resolves the two nonsecret LiveKit URLs needed
by the guarded QA launcher. `VOICE_QA_EXPECTED_LIVEKIT_URL` takes precedence over `LIVEKIT_URL` for
the worker connection. `LIVEKIT_PUBLIC_URL` supplies the browser-facing WSS origin.

Without those variables, the resolver requires a loopback `service/livekit` port-forward on 7880.
If argv omits context, its established peer must match the named `orbstack` API endpoint. Tailscale
HTTPS 8446 must target `http://127.0.0.1:17880`. The resolver returns the local worker URL and
`wss://<tailnet-dns>:8446`. The checks only read process, kubectl, and Tailscale status; they never
create, replace, or remove a listener or mapping.

The resolver raises `QaConfigError` with a specific code when a URL or topology cannot be proven.
UI origin and LiveKit credentials remain the responsibility of the QA runtime's existing Secret
configuration.
