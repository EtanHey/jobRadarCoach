"""Isolated PostgreSQL databases built from the repository migrations."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import uuid4

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


class DatabaseUnavailable(RuntimeError):
    """Raised when neither an explicit nor local Supabase database is available."""


def database_url() -> str:
    """Return the explicit test URL or privately discover the local Supabase URL."""

    if configured := os.environ.get("DATABASE_URL", "").strip():
        return configured
    try:
        status = subprocess.run(
            ["supabase", "status", "-o", "json"],
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        raise DatabaseUnavailable(
            "DATABASE_URL or a running local Supabase is required"
        ) from error
    if status.returncode != 0:
        raise DatabaseUnavailable(
            "DATABASE_URL or a running local Supabase is required"
        )
    try:
        discovered = json.loads(status.stdout)["DB_URL"]
    except (json.JSONDecodeError, KeyError, TypeError) as error:
        raise DatabaseUnavailable("local Supabase did not report DB_URL") from error
    if not isinstance(discovered, str) or not discovered.strip():
        raise DatabaseUnavailable("local Supabase reported an empty DB_URL")
    return discovered


def _migration_paths(migrations: Path, through: int) -> list[Path]:
    paths = sorted(migrations.glob("[0-9][0-9][0-9][0-9]_*.sql"))
    selected = [path for path in paths if int(path.name[:4]) <= through]
    numbers = [int(path.name[:4]) for path in selected]
    if numbers != list(range(1, through + 1)):
        raise ValueError(f"expected exactly migrations 0001 through {through:04d}")
    return selected


@contextmanager
def migrated_database(migrations: Path, *, through: int) -> Iterator[str]:
    """Create, migrate, and always remove an exact disposable sibling database."""

    source = database_url()
    parts = conninfo_to_dict(source)
    database_name = f"jobradar_test_{uuid4().hex}"
    admin_parts = {**parts, "dbname": "postgres"}
    test_parts = {**parts, "dbname": database_name}
    created = False
    try:
        with psycopg.connect(make_conninfo(**admin_parts), autocommit=True) as admin:
            admin.execute(
                sql.SQL("create database {} template template0").format(
                    sql.Identifier(database_name)
                )
            )
            created = True
        test_url = make_conninfo(**test_parts)
        with psycopg.connect(test_url) as connection:
            for migration in _migration_paths(migrations, through):
                connection.execute(migration.read_text(encoding="utf-8"))
                connection.commit()
        yield test_url
    finally:
        if created:
            with psycopg.connect(
                make_conninfo(**admin_parts), autocommit=True
            ) as admin:
                admin.execute(
                    "select pg_terminate_backend(pid) from pg_stat_activity "
                    "where datname=%s and pid<>pg_backend_pid()",
                    (database_name,),
                )
                admin.execute(
                    sql.SQL("drop database if exists {}").format(
                        sql.Identifier(database_name)
                    )
                )
