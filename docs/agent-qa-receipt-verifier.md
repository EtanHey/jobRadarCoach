# Agent QA receipt verifier

Before creating a voice-QA room, verify the agent's startup receipt against the live process and
LiveKit registration pool:

```sh
LIVEKIT_URL='ws://expected-livekit:7880' \
  python scripts/verify_agent_qa_receipt.py docs.local/voice-qa-agent-receipt.json
```

`LIVEKIT_URL` must exactly match the credential-free `ws://` or `wss://` server URL in the receipt.
Set `LIVEKIT_K8S_NAMESPACE` or `LIVEKIT_K8S_SELECTOR` only when the LiveKit deployment uses values
other than `job-radar-coach` and `app=livekit`.

The command is read-only. It inspects the receipt process and reads the LiveKit pod list and logs.
Success prints one compact JSON line containing `"status":"READY"` and exits zero. Failure prints
`NOT_READY <code> <detail>` to stderr and exits nonzero. Treat every nonzero exit as a closed gate;
do not create a QA room from that receipt.
