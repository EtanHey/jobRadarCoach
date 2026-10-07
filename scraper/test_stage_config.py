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
