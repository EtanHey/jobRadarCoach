# Agent receipt verifier

Released verifier SHA-256: `a1a94bfb4d379a95fe0bd3ec9960d4abf83744d1938971cb88c5b8c521feafa2`.
Pinned consumers must upgrade their invocation and output parser together when adopting this release.

Before creating a voice room, verify the agent receipt against the live process, current host load,
and LiveKit registration pool. Select the intended mode explicitly:

```sh
LIVEKIT_URL='ws://expected-livekit:7880' \
  python scripts/verify_agent_qa_receipt.py \
  --require-mode normal docs.local/voice-normal-agent-receipt.json
```

Use `--require-mode qa docs.local/voice-qa-agent-receipt.json` for a QA room. The agent uses
`AGENT_NORMAL_RECEIPT_FILE` and `VOICE_QA_RECEIPT_FILE` as the respective path overrides. The two
resolved paths must remain distinct.

`LIVEKIT_URL` must exactly match the credential-free `ws://` or `wss://` server URL in the receipt.
Set `LIVEKIT_K8S_NAMESPACE` or `LIVEKIT_K8S_SELECTOR` only when the LiveKit deployment uses values
other than `job-radar-coach` and `app=livekit`.

The command is read-only. It accepts schema versions 1 and 2. Version 1 is QA-only and cannot prove
the effective load threshold, so it fails closed with `threshold_unknown`. Version 2 binds the
requested mode and samples the current one-minute host load per CPU on every invocation; the
recorded startup load is informational.

Readiness also requires the receipt worker to be the sole automatic room worker in the current
LiveKit pool. Missing, named or non-room, and additional automatic workers fail closed.

Success exits zero and prints one compact JSON line:

```json
{"status":"READY","mode":"normal","worker_id":"AW_example"}
```

Failure exits nonzero, prints a stable reason as compact JSON on stdout, and writes detail to stderr:

```json
{"status":"NOT_READY","reason":"wrong_mode"}
```

Treat every nonzero exit as a closed gate; do not create a room from that receipt.
