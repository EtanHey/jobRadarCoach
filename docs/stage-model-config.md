# Extraction and scoring model settings

The shared resolver in `scraper/stage_config.py` configures both batch CLIs and
`jrc-analysis-worker`. Defaults are:

| Stage | Provider | Model | Reasoning effort |
| --- | --- | --- | --- |
| Extractor | codex | gpt-5.6-luna | xhigh |
| Scorer | codex | gpt-5.6-terra | xhigh |

Set `EXTRACTOR_PROVIDER`, `EXTRACTOR_MODEL`, `EXTRACTOR_REASONING_EFFORT`, or
`SCORER_PROVIDER`, `SCORER_MODEL`, `SCORER_REASONING_EFFORT` in the worker's
launch environment. Each stage resolves independently. For persisted config,
use profile fields `runtime.extractor.provider`, `runtime.extractor.model`,
`runtime.extractor.reasoning_effort` and their `runtime.scorer.*` equivalents.

For the local worker and batch CLIs, precedence is stage environment, stage profile, default.
Shared `BRAIN`, `CODEX_MODEL`, `CODEX_REASONING_EFFORT`, `OLLAMA_MODEL`, and
`runtime.brain` cannot override their independent stage settings.
`OLLAMA_BASE_URL` remains a transport setting for both paths. With no provider
setting, standalone jobs now default to Codex (previously Ollama).
Ollama defaults to `qwen2.5:7b-instruct` when selected without a model; reasoning
effort applies to Codex only. Blank explicit settings fail configuration.

Codex and Ollama have working adapters. Recognized future providers such as
Claude fail with `UnsupportedBrainError` before candidate selection; adding
an adapter belongs at the provider translation seam, without renaming stage
settings. Direct calls to the generic brain transport have vendor defaults
(`gpt-5.6`, `medium`); stage defaults live only in the stage resolver.

This source change does not install or restart the production analysis service.
