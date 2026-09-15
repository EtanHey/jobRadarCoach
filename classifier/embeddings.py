"""Pinned local job embeddings in a separate SQLite store."""

from __future__ import annotations

from array import array
from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import math
import os
from pathlib import Path
import sqlite3
import threading
from urllib.parse import urlsplit


MODEL_ID = "BAAI/bge-large-en-v1.5"
MODEL_REVISION = "d4aa6901d3a41ba39fb536a557fa166f842b0e09"
MAX_SCAN = 1000
_model = None
_model_lock = threading.Lock()


@dataclass(frozen=True)
class PreparedEmbedding:
    posting_id: str
    text: str
    content_sha256: str
    model_id: str = MODEL_ID
    model_revision: str = MODEL_REVISION


def require_local_database_url(database_url: str) -> None:
    parsed = urlsplit(database_url)
    if (parsed.scheme not in {"postgres", "postgresql"}
            or parsed.hostname not in {"localhost", "127.0.0.1"}):
        raise ValueError("DATABASE_URL must use localhost or 127.0.0.1")


def default_path(environment: Mapping[str, str] = os.environ) -> Path:
    configured = environment.get("JRC_EMBEDDINGS_PATH", "").strip()
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".local/share/jobradar-coach/job-embeddings.sqlite3"


def prepare(posting_id: str, title: str, raw_jd: str) -> PreparedEmbedding:
    if not all(isinstance(item, str) and item.strip() for item in (posting_id, title, raw_jd)):
        raise ValueError("posting id, title, and description must be nonblank strings")
    text = f"{title.strip()}\n{title.strip()}\n{raw_jd.strip()}"
    return PreparedEmbedding(posting_id, text, hashlib.sha256(text.encode()).hexdigest())


def capture_posting(connection, posting_id: str) -> PreparedEmbedding:
    row = connection.execute(
        "select p.id::text,p.title,p.raw_jd from public.postings p where p.id = %s",
        (posting_id,),
    ).fetchone()
    if row is None:
        raise LookupError("posting does not exist")
    return prepare(*row)


def _connect(path: Path) -> sqlite3.Connection:
    os.umask(0o077)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    connection = sqlite3.connect(path, timeout=30)
    connection.execute("pragma journal_mode=wal")
    connection.execute("pragma busy_timeout=30000")
    connection.execute(
        "create table if not exists job_embeddings ("
        "posting_id text not null, content_sha256 text not null, model_id text not null, "
        "model_revision text not null, dimensions integer not null, vector blob not null, "
        "embedded_at text not null default current_timestamp, "
        "primary key(posting_id,content_sha256,model_id,model_revision))"
    )
    return connection


def ensure_store(path: Path | None = None) -> None:
    with _connect(default_path() if path is None else path):
        pass


def _key(prepared: PreparedEmbedding) -> tuple[str, str, str, str]:
    return (prepared.posting_id, prepared.content_sha256, prepared.model_id, prepared.model_revision)


def _exists(connection: sqlite3.Connection, prepared: PreparedEmbedding) -> bool:
    return connection.execute(
        "select 1 from job_embeddings where posting_id=? and content_sha256=? "
        "and model_id=? and model_revision=?", _key(prepared),
    ).fetchone() is not None


def _load_model():
    global _model
    with _model_lock:
        if _model is None:
            from sentence_transformers import SentenceTransformer

            device = os.environ.get("JRC_EMBEDDINGS_DEVICE", "cpu").strip()
            if device not in {"cpu", "mps"}:
                raise ValueError("JRC_EMBEDDINGS_DEVICE must be cpu or mps")
            _model = SentenceTransformer(
                MODEL_ID, revision=MODEL_REVISION, device=device, local_files_only=True,
            )
        return _model


def embed_text(text: str) -> list[float]:
    vector = _load_model().encode(
        [text], normalize_embeddings=True, convert_to_numpy=True, show_progress_bar=False,
    )[0]
    return [float(value) for value in vector]


def embed_prepared(
    prepared: PreparedEmbedding, *, path: Path | None = None,
    embedder: Callable[[str], list[float]] = embed_text,
) -> str:
    sink = default_path() if path is None else path
    with _connect(sink) as connection:
        if _exists(connection, prepared):
            return "reused"
    vector = embedder(prepared.text)
    if not vector or not all(math.isfinite(value) for value in vector):
        raise ValueError("embedding must contain finite values")
    payload = array("f", vector).tobytes()
    with _connect(sink) as connection:
        cursor = connection.execute(
            "insert or ignore into job_embeddings "
            "(posting_id,content_sha256,model_id,model_revision,dimensions,vector) "
            "values(?,?,?,?,?,?)", (*_key(prepared), len(vector), payload),
        )
        return "stored" if cursor.rowcount == 1 else "reused"


def list_missing(connection, *, path: Path | None = None, limit: int = MAX_SCAN):
    if type(limit) is not int or not 1 <= limit <= MAX_SCAN:
        raise ValueError("limit must be between 1 and 1000")
    rows = connection.execute(
        "select p.id::text,p.title,p.raw_jd from public.postings p "
        "where p.raw_jd is not null and length(trim(p.raw_jd))>=80 "
        "order by coalesce(p.posted_at,p.first_seen_at) desc,p.id limit %s", (MAX_SCAN,),
    ).fetchall()
    prepared = [prepare(*row) for row in rows]
    sink = default_path() if path is None else path
    with _connect(sink) as sqlite:
        return [item for item in prepared if not _exists(sqlite, item)][:limit]


def embed_missing(
    connection, *, path: Path | None = None, limit: int = 6,
    embedder: Callable[[str], list[float]] = embed_text,
    on_failure: Callable[[str, str], None] | None = None,
) -> tuple[int, int]:
    stored = failed = 0
    for prepared in list_missing(connection, path=path, limit=limit):
        try:
            embed_prepared(prepared, path=path, embedder=embedder)
            stored += 1
        except Exception as error:
            failed += 1
            if on_failure:
                on_failure(prepared.posting_id, type(error).__name__)
    return stored, failed
