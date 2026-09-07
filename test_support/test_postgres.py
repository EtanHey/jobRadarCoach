from __future__ import annotations

import subprocess

import pytest

from test_support import postgres


@pytest.mark.parametrize(
    "failure",
    [FileNotFoundError("supabase"), subprocess.TimeoutExpired("supabase", 10)],
)
def test_database_url_converts_status_launch_failures(
    monkeypatch, failure: Exception
) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)

    def fail(*_args, **kwargs):
        assert kwargs["timeout"] == 10
        raise failure

    monkeypatch.setattr(subprocess, "run", fail)

    with pytest.raises(postgres.DatabaseUnavailable) as raised:
        postgres.database_url()

    assert raised.value.__cause__ is failure
