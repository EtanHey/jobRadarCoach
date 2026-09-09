# Voice agent dependencies

Use Python 3.13 for the verified runtime. `requirements.txt` pins direct runtime
and test dependencies; it is not a complete transitive lockfile. The agent remains
a set of scripts, started from the repository root.

```sh
python3.13 -m venv .venv-agent
.venv-agent/bin/python -m pip install -r agent/requirements.txt
.venv-agent/bin/python -m unittest discover -s agent -p 'test_*.py'
```

Use the managed `jrc` lifecycle to start a room worker. Console mode does not
join LiveKit rooms. QA needs a fresh mode-aware receipt and registration-pool
verification before any room join; installing dependencies does not establish
readiness. Secrets belong in the runtime environment, never in this file.

For local semantic turn detection, set `HF_HOME` and `HF_HUB_CACHE` to the
runtime's owned cache and leave `LIVEKIT_REMOTE_EOT_URL` unset. Prepare assets
before starting the worker:

```sh
.venv-agent/bin/python -m livekit.agents download-files
```

Importing the turn-detector package registers both English and multilingual
inference runners. Startup initializes both, so the cache needs
`livekit/turn-detector` revisions `v1.2.2-en` and `v0.4.1-intl`, including their
tokenizers, language metadata and `onnx/model_q8.onnx` files.

WhisperLiveKit runs in a separate environment. Do not install its Torch/MLX
server dependencies into this agent environment. Coordinate model loading and
synthesis windows with the lifecycle owner, and remove owned processes and
temporary environments after QA while preserving borrowed services.
