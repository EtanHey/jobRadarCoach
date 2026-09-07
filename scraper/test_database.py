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
    connection.execute("select 1")  # Enclose helper transactions in a rollback boundary.
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


def test_annotation_profile_rebuilds_local_contract_without_empty_depth() -> None:
    snapshot = {
        "contract_version": 1,
        "candidate.positioning": "Builder",
        "candidate.tenure_years": 6,
        "candidate.location": "Here",
        "candidate.fit_terms": ["react"],
        "candidate.open_to.geographies": ["There"],
        "candidate.open_to.work_modes": ["remote"],
        "candidate.open_to.relocation": None,
        "candidate.preferences.product_company": None,
        "candidate.preferences.experience_gap": None,
        "candidate.professional_depth": {},
        "fit_signals": [],
        "constraints.global_never_claims": ["private"],
        "constraints.evidence_scoped_prohibitions": {},
    }

    profile = database.annotation_profile(snapshot)

    assert "professional_depth" not in profile["candidate"]
    assert profile["candidate"]["open_to"]["geographies"] == ["There"]
    assert profile["constraints"]["global_never_claims"] == ["private"]


def test_posting_upsert_preserves_rich_fields_identity_and_status(connection) -> None:
    external_id = "lane2d-upsert-preservation"
    connection.execute(
        "delete from public.postings where source = 'test' and external_id = %s",
        (external_id,),
    )
    rich = {
        "source": "test", "id": external_id,
        "url": "https://example.test/old", "title": "Old title", "company": "Old Co",
        "location": "Old place", "remote": True, "seniority": "senior",
        "stack": ["TypeScript"], "salary": "100", "apply_url": "https://apply.test/old",
        "posted_at": "2026-09-01T10:00:00Z", "jd_text": "A sufficiently rich description.",
        "alive": True, "liveness_status": 200, "liveness_reason": "http-live",
        "liveness_final_url": "https://example.test/old",
        "liveness_checked_at": "2026-09-07T09:59:00Z",
    }
    [posting_id] = database.persist_postings(
        connection, [rich], "2026-09-07T10:00:00Z"
    )
    connection.execute(
        "update public.posting_status set status = 'saved' where posting_id = %s",
        (posting_id,),
    )
    thin = {
        "source": "test", "id": external_id,
        "url": "https://example.test/new", "title": "New title", "company": "New Co",
        "location": "New place", "posted_at": "not-a-timestamp",
        "seniority": "unknown", "stack": ["unknown"], "alive": None,
        "liveness_status": 500, "liveness_reason": "http-500-uncertain",
        "liveness_final_url": "https://example.test/new",
        "liveness_checked_at": "2026-09-07T10:59:00Z",
    }
    [repeated_id] = database.persist_postings(
        connection, [thin], "2026-09-07T11:00:00Z"
    )
    database.persist_postings(connection, [{
        **thin, "alive": "unknown", "liveness_status": "unknown",
        "liveness_reason": "unknown", "liveness_final_url": 42,
        "liveness_checked_at": "not-a-timestamp",
    }], "2026-09-07T12:00:00Z")

    database.persist_postings(connection, [{
        **thin, "alive": False, "liveness_status": 404,
        "liveness_reason": "http-404",
        "liveness_checked_at": "2026-09-07T09:00:00Z",
    }], "2026-09-07T09:00:00Z")

    row = connection.execute(
        "select id::text, url, title, company, location, remote, seniority, stack, "
        "salary, apply_url, posted_at::text, raw_jd, first_seen_at::text, "
        "last_seen_at::text, liveness from public.postings where id = %s",
        (posting_id,),
    ).fetchone()
    assert repeated_id == posting_id
    assert row[1:12] == (
        "https://example.test/new", "New title", "New Co", "New place", True,
        "senior", ["TypeScript"], "100", "https://apply.test/old",
        "2026-09-01 10:00:00+00", "A sufficiently rich description.",
    )
    assert row[12] == "2026-09-07 10:00:00+00"
    assert row[13] == "2026-09-07 12:00:00+00"
    assert row[14] == {
        "alive": True, "liveness_status": 200, "liveness_reason": "http-live",
        "liveness_final_url": "https://example.test/old",
        "liveness_checked_at": "2026-09-07T09:59:00Z",
    }
    assert connection.execute(
        "select status from public.posting_status where posting_id = %s", (posting_id,)
    ).fetchone() == ("saved",)
    assert connection.execute(
        "select count(*) from public.posting_scores where posting_id = %s", (posting_id,)
    ).fetchone() == (0,)
    connection.execute(
        "update public.postings set liveness = %s::jsonb where id = %s",
        ('{"liveness_checked_at":"invalid"}', posting_id),
    )
    database.persist_postings(connection, [{
        **rich, "alive": False, "liveness_status": 404,
        "liveness_checked_at": "2026-09-07T13:00:00Z",
    }], "2026-09-07T13:00:00Z")
    assert connection.execute(
        "select liveness->'alive' from public.postings where id = %s", (posting_id,)
    ).fetchone() == (False,)


@pytest.mark.parametrize("field,value", [
    ("id", None), ("url", None), ("title", None), ("company", None),
    ("id", "\t\n"),
])
def test_required_posting_strings_fail_before_coercion_and_roll_back(
    connection, field: str, value: object
) -> None:
    prefix = "lane2d-atomic"
    connection.execute(
        "delete from public.postings where source = 'test' and external_id like %s",
        (prefix + "%",),
    )
    valid = {
        "source": "test", "id": prefix + "-valid", "url": "https://example.test/1",
        "title": "Engineer", "company": "Example",
    }
    invalid = {
        **valid, "id": prefix + "-invalid", "url": "https://example.test/2",
        field: value,
    }

    with pytest.raises(ValueError, match=field):
        database.persist_postings(
            connection, [valid, invalid], "2026-09-07T12:00:00Z"
        )

    assert connection.execute(
        "select count(*) from public.postings where source = 'test' "
        "and external_id like %s", (prefix + "%",)
    ).fetchone() == (0,)
    assert connection.execute(
        "select count(*) from public.postings where source = 'test' "
        "and external_id = 'None'"
    ).fetchone() == (0,)


def test_first_insert_falls_back_to_posting_url_for_apply_url(connection) -> None:
    posting = {
        "source": "test", "id": "lane2d-apply-fallback",
        "url": "https://example.test/fallback", "title": "Engineer",
        "company": "Example",
    }

    [posting_id] = database.persist_postings(
        connection, [posting], "2026-09-07T12:00:00Z"
    )

    assert connection.execute(
        "select apply_url from public.postings where id = %s", (posting_id,)
    ).fetchone() == ("https://example.test/fallback",)
