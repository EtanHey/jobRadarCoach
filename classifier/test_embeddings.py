from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sqlite3
import threading

import pytest

from classifier import embeddings


class Rows:
    def __init__(self, rows):
        self.rows = rows

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class PostingConnection:
    def __init__(self, rows):
        self.rows = rows
        self.queries = []

    def execute(self, query, params=()):
        self.queries.append((query, params))
        if "where p.id = %s" in query:
            wanted = params[0]
            return Rows([row for row in self.rows if row[0] == wanted])
        return Rows(self.rows)


def row(posting_id="job-1", title="Engineer", jd="Build useful systems"):
    return posting_id, title, jd


def logical_rows(path: Path) -> int:
    with sqlite3.connect(path) as connection:
        return connection.execute("select count(*) from job_embeddings").fetchone()[0]


def test_key_reuses_content_and_invalidates_jd_or_model(tmp_path) -> None:
    path = tmp_path / "vectors.sqlite3"
    calls = []

    def embed(text):
        calls.append(text)
        return [1.0, 2.0]

    first = embeddings.prepare(*row())
    assert embeddings.embed_prepared(first, path=path, embedder=embed) == "stored"
    assert embeddings.embed_prepared(first, path=path, embedder=embed) == "reused"
    changed = embeddings.prepare(*row(jd="A changed description"))
    assert embeddings.embed_prepared(changed, path=path, embedder=embed) == "stored"
    changed_model = embeddings.PreparedEmbedding(
        changed.posting_id, changed.text, changed.content_sha256,
        "replacement/model", "revision-2",
    )
    assert embeddings.embed_prepared(changed_model, path=path, embedder=embed) == "stored"
    assert len(calls) == 3
    assert logical_rows(path) == 3


@pytest.mark.parametrize("host", ["db.example.com", "10.0.0.8", "::1", ""])
def test_remote_or_unknown_database_url_is_refused(host) -> None:
    url = "postgresql://user@/jobs" if not host else f"postgresql://user@{host}/jobs"
    with pytest.raises(ValueError, match="localhost"):
        embeddings.require_local_database_url(url)


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1"])
def test_local_database_url_is_allowed(host) -> None:
    embeddings.require_local_database_url(f"postgresql://user@{host}:5432/jobs")


def test_crash_and_concurrency_leave_one_logical_row(tmp_path) -> None:
    path = tmp_path / "vectors.sqlite3"
    prepared = embeddings.prepare(*row())
    with pytest.raises(RuntimeError, match="crash"):
        embeddings.embed_prepared(
            prepared, path=path, embedder=lambda _text: (_ for _ in ()).throw(RuntimeError("crash")),
        )
    barrier = threading.Barrier(2)

    def racing_embed(_text):
        barrier.wait()
        return [0.25, 0.75]

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(
            lambda _: embeddings.embed_prepared(prepared, path=path, embedder=racing_embed),
            range(2),
        ))
    assert sorted(outcomes) == ["reused", "stored"]
    assert logical_rows(path) == 1


def test_missing_scan_includes_already_scored_and_stale_content(tmp_path) -> None:
    path = tmp_path / "vectors.sqlite3"
    connection = PostingConnection([row("scored"), row("new")])
    old = embeddings.prepare(*row("scored", jd="old text"))
    embeddings.embed_prepared(old, path=path, embedder=lambda _text: [1.0])

    missing = embeddings.list_missing(connection, path=path, limit=10)

    assert [item.posting_id for item in missing] == ["scored", "new"]
    assert "posting_scores" not in connection.queries[0][0]


def test_title_is_weighted_twice_and_sink_is_only_sqlite(tmp_path) -> None:
    prepared = embeddings.capture_posting(PostingConnection([row()]), "job-1")
    assert prepared.text == "Engineer\nEngineer\nBuild useful systems"
    assert not hasattr(embeddings.embed_prepared, "postgres_connection")
    assert embeddings.default_path({"JRC_EMBEDDINGS_PATH": str(tmp_path / "x")}) == tmp_path / "x"
