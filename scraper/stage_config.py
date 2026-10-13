"""Stage-owned model policy, translated at the provider transport boundary.

Stage environment keys override runtime.<stage>.<field> profile settings,
then optional legacy transport settings for standalone jobs. Add future provider
adapters here; do not silently route an unimplemented provider through Codex or Ollama.
"""
from __future__ import annotations

import os
from collections.abc import Mapping

from scraper.brain_contract import BrainConfigurationError, resolve_brain

EXTRACTOR_PROVIDER = 'codex'
EXTRACTOR_MODEL = 'gpt-5.6-luna'
EXTRACTOR_REASONING_EFFORT = 'xhigh'
SCORER_PROVIDER = 'codex'
SCORER_MODEL = 'gpt-5.6-terra'
SCORER_REASONING_EFFORT = 'xhigh'
DEFAULTS = {
    'extractor': (EXTRACTOR_PROVIDER, EXTRACTOR_MODEL, EXTRACTOR_REASONING_EFFORT),
    'scorer': (SCORER_PROVIDER, SCORER_MODEL, SCORER_REASONING_EFFORT),
}
PROFILE_FIELDS = ('runtime.brain',) + tuple(
    f'runtime.{stage}.{field}' for stage in DEFAULTS
    for field in ('provider', 'model', 'reasoning_effort')
)


def load_stage_profile(connection) -> dict[str, object]:
    # Separate reads retain compatibility with the existing single-row profile API.
    profile = {}
    for field in PROFILE_FIELDS:
        row = connection.execute(
            'select value from public.profile where field = %s', (field,),
        ).fetchone()
        if row is not None:
            profile[field] = row[0]
    return profile


def stage_settings(stage: str, profile: Mapping[str, object],
                   env: Mapping[str, str] | None = None, *,
                   allow_legacy: bool = True) -> dict[str, str]:
    from scraper.brain import DEFAULT_OLLAMA_MODEL

    source = os.environ if env is None else env
    default_provider, default_model, default_effort = DEFAULTS[stage]
    def value(field, legacy, default):
        env_key = f'{stage.upper()}_{field.upper()}'
        profile_key = f'runtime.{stage}.{field}'
        fallback = source.get(legacy, default) if allow_legacy else default
        selected = source.get(env_key, profile.get(profile_key, fallback))
        if not isinstance(selected, str) or not selected.strip():
            raise BrainConfigurationError(f'{env_key} must be a nonblank string')
        return selected.strip()
    provider = resolve_brain(env={'BRAIN': value(
        'provider', 'BRAIN',
        profile.get('runtime.brain', default_provider) if allow_legacy else default_provider,
    )})
    settings = {'BRAIN': provider}
    if provider in ('codex', 'ollama'):
        model_key = 'CODEX_MODEL' if provider == 'codex' else 'OLLAMA_MODEL'
        fallback_model = default_model if provider == 'codex' else DEFAULT_OLLAMA_MODEL
        settings[model_key] = value('model', model_key, fallback_model)
    if provider == 'codex':
        settings['CODEX_REASONING_EFFORT'] = value(
            'reasoning_effort', 'CODEX_REASONING_EFFORT', default_effort,
        )
    if 'OLLAMA_BASE_URL' in source:
        settings['OLLAMA_BASE_URL'] = source['OLLAMA_BASE_URL']
    return settings
