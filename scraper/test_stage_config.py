"""Synthetic stage routing regressions; no model or database access."""
import pytest

from classifier import job as scorer
from extractor import job as extractor
from scripts import local_analysis
from classifier.test_job import Connection as ScoreConnection
from extractor.test_job import Connection as ExtractConnection


@pytest.mark.parametrize('stage,model', [('extractor', 'gpt-5.6-luna'), ('scorer', 'gpt-5.6-terra')])
def test_defaults(stage, model):
    from scraper.stage_config import stage_settings
    settings = stage_settings(stage, {}, {})
    assert settings == {'BRAIN': 'codex', 'CODEX_MODEL': model, 'CODEX_REASONING_EFFORT': 'xhigh'}


@pytest.mark.parametrize('stage', ['extractor', 'scorer'])
def test_stage_env_overrides_config_and_legacy_without_cross_talk(stage):
    from scraper.stage_config import stage_settings
    prefix = stage.upper()
    settings = stage_settings(stage, {f'runtime.{stage}.model': 'config-model'}, {
        f'{prefix}_PROVIDER': 'ollama', f'{prefix}_MODEL': 'synthetic-model',
        f'{prefix}_REASONING_EFFORT': 'low', 'BRAIN': 'codex',
        'CODEX_MODEL': 'legacy-model', 'PRIVATE_ENV': 'sentinel',
        ('SCORER_MODEL' if stage == 'extractor' else 'EXTRACTOR_MODEL'): 'other-stage',
    })
    assert settings == {'BRAIN': 'ollama', 'OLLAMA_MODEL': 'synthetic-model'}


def test_config_and_legacy_precedence():
    from scraper.stage_config import stage_settings
    assert stage_settings('scorer', {'runtime.scorer.provider': 'ollama', 'runtime.scorer.model': 'config'}, {}) == {'BRAIN': 'ollama', 'OLLAMA_MODEL': 'config'}
    assert stage_settings('scorer', {'runtime.brain': 'ollama'}, {'BRAIN': 'codex', 'CODEX_MODEL': 'legacy'})['CODEX_MODEL'] == 'legacy'


def test_scorer_dispatch_respects_stage_override():
    captured = []
    def score(connection, posting_id, *, brain_runner):
        brain_runner(object(), {})
        return 'stored'
    scorer.run_batch(ScoreConnection(), limit=1, timeout_seconds=10,
        env={'SCORER_PROVIDER': 'codex', 'SCORER_MODEL': 'synthetic-score', 'SCORER_REASONING_EFFORT': 'low'},
        candidate_lister=lambda *a, **kw: ['synthetic'], scorer=score,
        brain=lambda *a, **kw: captured.append(kw['env']))
    assert captured[0]['CODEX_MODEL'] == 'synthetic-score'
    assert captured[0]['CODEX_REASONING_EFFORT'] == 'low'


def test_extractor_dispatch_respects_stage_override(monkeypatch):
    captured = []
    def extract(posting, profile, *, runner, timeout_seconds):
        runner(object(), profile)
        return {'brain': 'codex', 'model': 'synthetic-extract'}
    monkeypatch.setattr(extractor, 'extract_posting', extract)
    monkeypatch.setattr(extractor, 'run_brain', lambda *a, **kw: captured.append(kw['env']))
    extractor.run_batch(ExtractConnection(), limit=1, timeout_seconds=10,
        env={'EXTRACTOR_PROVIDER': 'codex', 'EXTRACTOR_MODEL': 'synthetic-extract', 'EXTRACTOR_REASONING_EFFORT': 'high'},
        persister=lambda *a: 'stored')
    assert captured[0]['CODEX_MODEL'] == 'synthetic-extract'
    assert captured[0]['CODEX_REASONING_EFFORT'] == 'high'


@pytest.mark.parametrize('stage', ['extract', 'score'])
def test_local_worker_does_not_replace_stage_environment(monkeypatch, stage):
    captured = []
    module = extractor if stage == 'extract' else scorer
    monkeypatch.setattr(module, 'run_batch', lambda *a, **kw: captured.append(kw) or 0)
    local_analysis._run_stage(object(), stage, 'synthetic', 10, embeddings_enabled=False)
    assert 'env' not in captured[0]


def test_profile_loader_reads_committed_stage_fields():
    from scraper.stage_config import load_stage_profile
    from classifier.test_job import Result
    values = {'runtime.scorer.provider': 'ollama', 'runtime.scorer.model': 'config-score'}
    class ProfileConnection:
        def execute(self, query, params):
            assert 'public.profile' in query
            return Result((values[params[0]],) if params[0] in values else None)
    assert load_stage_profile(ProfileConnection()) == values


@pytest.mark.parametrize('value', ['', ' ', None])
def test_invalid_explicit_config_does_not_fall_back(value):
    from scraper.stage_config import stage_settings
    from scraper.brain_contract import BrainConfigurationError
    with pytest.raises(BrainConfigurationError):
        stage_settings('scorer', {'runtime.scorer.model': value}, {})


def test_future_provider_remains_explicitly_unsupported(capsys):
    assert scorer.run_batch(ScoreConnection(), limit=1, timeout_seconds=10,
        env={'SCORER_PROVIDER': 'claude', 'SCORER_MODEL': 'synthetic-future'},
        candidate_lister=lambda *a, **kw: pytest.fail('must not select')) == 1
    assert 'UnsupportedBrainError' in capsys.readouterr().out


@pytest.mark.parametrize('stage,model', [('extract', 'gpt-5.6-luna'), ('score', 'gpt-5.6-terra')])
@pytest.mark.parametrize('embeddings_enabled', [False, True])
@pytest.mark.parametrize('legacy', ['profile', 'model', 'all'])
@pytest.mark.parametrize('override', [None, 'env', 'profile'])
def test_local_worker_ignores_stage_agnostic_settings(monkeypatch, stage, model,
                                                     embeddings_enabled, legacy, override):
    from functools import partial
    for key in ('BRAIN', 'CODEX_MODEL', 'CODEX_REASONING_EFFORT', 'OLLAMA_MODEL',
                'EXTRACTOR_PROVIDER', 'EXTRACTOR_MODEL', 'EXTRACTOR_REASONING_EFFORT',
                'SCORER_PROVIDER', 'SCORER_MODEL', 'SCORER_REASONING_EFFORT'):
        monkeypatch.delenv(key, raising=False)
    if legacy in ('model', 'all'):
        monkeypatch.setenv('CODEX_MODEL', 'x')
    if legacy == 'all':
        monkeypatch.setenv('BRAIN', 'ollama')
        monkeypatch.setenv('OLLAMA_MODEL', 'shared-model')
        monkeypatch.setenv('CODEX_REASONING_EFFORT', 'low')
    stage_name = 'extractor' if stage == 'extract' else 'scorer'
    effort = 'xhigh'
    if override:
        model = f'synthetic-{stage_name}'
        effort = 'high'
        if override == 'env':
            monkeypatch.setenv(f'{stage_name.upper()}_PROVIDER', 'codex')
            monkeypatch.setenv(f'{stage_name.upper()}_MODEL', model)
            monkeypatch.setenv(f'{stage_name.upper()}_REASONING_EFFORT', effort)
        else:
            module = extractor if stage == 'extract' else scorer
            loader = module.load_runtime_profile
            monkeypatch.setattr(module, 'load_runtime_profile', lambda connection: {
                **loader(connection), f'runtime.{stage_name}.provider': 'codex',
                f'runtime.{stage_name}.model': model,
                f'runtime.{stage_name}.reasoning_effort': effort,
            })
    brain = 'ollama' if legacy in ('profile', 'all') else 'codex'
    captured = []
    def transport(*args, **kwargs):
        captured.append(kwargs['env'])
    if stage == 'extract':
        connection = ExtractConnection(brain=brain)
        def extract(posting, profile, *, runner, timeout_seconds):
            runner(object(), profile)
            return {'brain': 'codex', 'model': model}
        monkeypatch.setattr(extractor, 'extract_posting', extract)
        monkeypatch.setattr(extractor, 'run_brain', transport)
        monkeypatch.setattr(extractor, 'run_batch', partial(
            extractor.run_batch, persister=lambda *a: 'stored'))
        from extractor.test_job import POSTING_IDS
    else:
        connection = ScoreConnection(brain=brain)
        def score(connection, posting_id, *, brain_runner):
            brain_runner(object(), {})
            return 'stored'
        monkeypatch.setattr(scorer, 'run_batch', partial(
            scorer.run_batch, candidate_lister=lambda *a, **kw: [kw['posting_ids'][0]],
            scorer=score, brain=transport))
        monkeypatch.setattr(local_analysis.job_embeddings, 'capture_posting', lambda *a: None)
        from classifier.test_job import POSTING_IDS
    assert local_analysis._run_stage(connection, stage, POSTING_IDS[0], 10,
                                    embeddings_enabled=embeddings_enabled) == 0
    assert captured == [{'BRAIN': 'codex', 'CODEX_MODEL': model,
                         'CODEX_REASONING_EFFORT': effort}]


@pytest.mark.parametrize('stage', ['extractor', 'scorer'])
def test_worker_policy_allows_explicit_ollama_without_legacy_model(stage):
    from scraper.brain import DEFAULT_OLLAMA_MODEL
    from scraper.stage_config import stage_settings
    assert stage_settings(stage, {}, {
        f'{stage.upper()}_PROVIDER': 'ollama', 'OLLAMA_MODEL': 'shared-model',
        'OLLAMA_BASE_URL': 'http://localhost:11434',
    }, allow_legacy=False) == {
        'BRAIN': 'ollama', 'OLLAMA_MODEL': DEFAULT_OLLAMA_MODEL,
        'OLLAMA_BASE_URL': 'http://localhost:11434',
    }


@pytest.mark.parametrize('stage,model', [('extractor', 'gpt-5.6-luna'), ('scorer', 'gpt-5.6-terra')])
@pytest.mark.parametrize('legacy', ['BRAIN', 'runtime.brain', 'CODEX_MODEL', 'CODEX_REASONING_EFFORT'])
@pytest.mark.parametrize('override', [None, 'env', 'profile'])
def test_cli_main_ignores_shared_settings(monkeypatch, stage, model, legacy, override):
    from contextlib import nullcontext
    from functools import partial
    from unittest.mock import patch
    import os
    import psycopg
    module = extractor if stage == 'extractor' else scorer
    connection = ExtractConnection() if stage == 'extractor' else ScoreConnection()
    profile = {'runtime.brain': 'ollama'} if legacy == 'runtime.brain' else {}
    environment = {'DATABASE_URL': 'postgresql://synthetic.invalid/db'}
    if legacy != 'runtime.brain':
        environment[legacy] = {'BRAIN': 'ollama', 'CODEX_MODEL': 'shared-model',
                               'CODEX_REASONING_EFFORT': 'low'}[legacy]
    expected = {'BRAIN': 'codex', 'CODEX_MODEL': model, 'CODEX_REASONING_EFFORT': 'xhigh'}
    if override:
        values = {'provider': 'codex', 'model': f'synthetic-{stage}', 'reasoning_effort': 'high'}
        expected.update(CODEX_MODEL=values['model'], CODEX_REASONING_EFFORT='high')
        if override == 'env':
            environment.update({f'{stage.upper()}_{key.upper()}': value for key, value in values.items()})
        else:
            profile.update({f'runtime.{stage}.{key}': value for key, value in values.items()})
    monkeypatch.setattr(psycopg, 'connect', lambda *a, **kw: nullcontext(connection))
    monkeypatch.setattr(module, 'load_runtime_profile', lambda *a: profile)
    captured = []
    transport = lambda *a, **kw: captured.append(kw['env'])
    if stage == 'extractor':
        def extract(posting, profile, *, runner, timeout_seconds):
            runner(object(), profile)
            return {'brain': 'codex', 'model': expected['CODEX_MODEL']}
        monkeypatch.setattr(extractor, 'extract_posting', extract)
        monkeypatch.setattr(extractor, 'run_brain', transport)
        monkeypatch.setattr(module, 'run_batch', partial(module.run_batch, persister=lambda *a: 'stored'))
    else:
        def score(connection, posting_id, *, brain_runner):
            brain_runner(object(), {})
            return 'stored'
        monkeypatch.setattr(module, 'run_batch', partial(module.run_batch,
            candidate_lister=lambda *a, **kw: ['synthetic'], scorer=score, brain=transport))
    with patch.dict(os.environ, environment, clear=True):
        assert module.main(['--limit', '1', '--timeout-seconds', '10']) == 0
    assert captured == [expected]
