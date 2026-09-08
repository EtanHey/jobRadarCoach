# Guarded QA runtime adapter

`QaRuntimeService` owns one loopback QA proxy and optionally one unused Tailscale HTTPS mapping.
It requires a fresh successful coach receipt verifier before starting. The Node launcher repeats
verification on each readiness/token callback; a prior successful run does not authorize a new run.
A supplied `receipt_provider(context)` selects the receipt from the preceding QA worker service.
Without a provider, `VOICE_QA_RECEIPT_FILE` or the documented repository default is used.

The adapter reads credential values into child environment only, derives nonsecret URL defaults
through `runtime_qa_config`, and records no credentials in its ownership identity. Session, worker,
process birth and supervisor identity bind readiness. `VOICE_QA_PHONE=1` selects an unused HTTPS
port in 8450–8499; existing UI and LiveKit mappings are never replaced.

Cleanup verifies the exact current mapping target, stops the owned proxy, and removes its marker.
Unknown mapping status is not proof of absence. A possibly applied mapping is retained as a partial
start identity until cleanup is confirmed; a replacement mapping is never removed.

This slice supplies the adapter. The lifecycle stack supplies shared prerequisites, worker startup,
the deployed `/mic` availability check, and command wiring. It does not itself start a room worker.
