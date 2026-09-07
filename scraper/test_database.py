from __future__ import annotations

import os
from pathlib import Path

import pytest

from scraper import database


psycopg = pytest.importorskip("psycopg")


@pytest.fixture
def connection():
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        pytest.skip("DATABASE_URL is required for real profile DB tests")
    connection = psycopg.connect(database_url)
    try:
        yield connection
    finally:
        connection.rollback()
        connection.close()


def write_public_seed(tmp_path: Path) -> tuple[Path, Path]:
    root = Path(__file__).resolve().parent.parent
    profile_path = tmp_path / "profile.yaml"
    profile_path.write_text(
        (root / "profile.example.yaml").read_text(encoding="utf-8").replace(
            "Example City", "Public City"
        ),
        encoding="utf-8",
    )
    searches_path = tmp_path / "searches.yaml"
    searches_path.write_text(
        (root / "scraper" / "searches.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    return profile_path, searches_path


def test_runtime_only_bootstraps_full_profile_then_db_wins(connection, tmp_path: Path) -> None:
    profile_path, searches_path = write_public_seed(tmp_path)
    connection.execute("delete from public.profile")
    connection.execute(
        "insert into public.profile (field, value) values ('runtime.brain', '\"codex\"')"
    )

    snapshot = database.load_or_seed_profile(connection, profile_path, searches_path)

    assert database.REQUIRED_PROFILE_FIELDS <= snapshot.keys()
    assert snapshot["runtime.brain"] == "codex"
    assert snapshot["candidate.professional_depth"] == {}
    connection.execute(
        "select public.update_profile('search.terms', '[\"DB edited role\"]')"
    )
    profile_path.unlink()
    searches_path.unlink()
    repeated = database.load_or_seed_profile(connection, profile_path, searches_path)
    assert repeated["search.terms"] == ["DB edited role"]
    assert repeated["runtime.brain"] == "codex"


def test_validation_failure_rolls_back_every_missing_insert(
    connection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile_path, searches_path = write_public_seed(tmp_path)
    connection.execute("delete from public.profile")
    connection.execute(
        "insert into public.profile (field, value) values ('runtime.brain', '\"ollama\"')"
    )
    seed = database.build_profile_seed(profile_path, searches_path)
    seed["candidate.positioning"] = "\t\n"
    monkeypatch.setattr(database, "build_profile_seed", lambda *_args: seed)

    with pytest.raises(ValueError, match="candidate.positioning"):
        database.load_or_seed_profile(connection, profile_path, searches_path)

    rows = connection.execute("select field from public.profile order by field").fetchall()
    assert rows == [("runtime.brain",)]


def test_shipped_example_placeholders_cannot_seed(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="placeholders"):
        database.build_profile_seed(
            Path(__file__).resolve().parent.parent / "profile.example.yaml",
            Path(__file__).resolve().parent / "searches.yaml",
        )


def test_operational_searches_use_one_db_snapshot() -> None:
    assert database.searches_from_profile({
        "search.terms": ["One", "Two"],
        "candidate.open_to.geographies": ["Here", "Remote"],
        "search.recency": "r3600",
    }) == [
        {"keywords": "One", "location": "Here", "recency": "r3600"},
        {"keywords": "One", "location": "Remote", "recency": "r3600"},
        {"keywords": "Two", "location": "Here", "recency": "r3600"},
        {"keywords": "Two", "location": "Remote", "recency": "r3600"},
    ]
