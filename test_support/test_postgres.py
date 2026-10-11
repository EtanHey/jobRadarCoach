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


def test_only_reserved_migration_gap_is_allowed(tmp_path):
    for number in range(1, 32):
        if number != 30:
            (tmp_path / f"{number:04d}_synthetic.sql").touch()
    assert len(postgres._migration_paths(tmp_path, through=31)) == 30
    with pytest.raises(ValueError):
        postgres._migration_paths(tmp_path, through=30)
    (tmp_path / "0030_synthetic.sql").touch()
    assert len(postgres._migration_paths(tmp_path, through=31)) == 31
    (tmp_path / "0028_synthetic.sql").unlink()
    with pytest.raises(ValueError):
        postgres._migration_paths(tmp_path, through=31)
