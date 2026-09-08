from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path

import pytest

from classifier import persistence
from classifier.test_core import profile_snapshot

psycopg = pytest.importorskip("psycopg")
from test_support.postgres import DatabaseUnavailable, migrated_database  # noqa: E402


ROOT = Path(__file__).parents[1]
MIGRATIONS = ROOT / "supabase/migrations"
REGRESSION = ROOT / "supabase/tests/0007_status_pipeline_test.sql"
LEGACY_IDS = [f"00000000-0000-0000-0000-{number}" for number in (
    "000000007101", "000000007102", "000000007103",
)]
CAPTURE_ID = "00000000-0000-0000-0000-000000007104"


def test_legacy_migration_and_plain_sql_status_pipeline() -> None:
    try:
        database = migrated_database(MIGRATIONS, through=6)
        with database as url, psycopg.connect(url) as connection:
            for number, posting_id in enumerate(LEGACY_IDS, 1):
                connection.execute(
                    "insert into public.postings "
                    "(id,source,external_id,url,title,company) values "
                    "(%s,'legacy-status',%s,%s,%s,'Legacy Status Co')",
                    (
                        posting_id,
                        f"legacy-{number}",
                        f"https://example.test/legacy-{number}",
                        f"Legacy role {number}",
                    ),
                )
            connection.execute(
                "insert into public.posting_status "
                "(posting_id,status,reason,updated_at) values "
                "(%s,'saved','saved verbatim','2001-01-01Z'),"
                "(%s,'rejected','  ruled out verbatim  ','2002-01-01Z'),"
                "(%s,'applied','legacy stale reason','2003-01-01Z')",
                LEGACY_IDS,
            )
            connection.execute(
                "insert into public.application_history "
                "(id,posting_id,company,role,application_date,outcome,recorded_at) "
                "values ('00000000-0000-0000-0000-000000007111',%s,"
                "'Explicit History Co','Engineer','2020-02-03','interviewed',"
                "'2020-02-04Z')",
                (LEGACY_IDS[2],),
            )
            connection.commit()

            connection.execute(
                (MIGRATIONS / "0007_status_pipeline.sql").read_text(encoding="utf-8")
            )
            connection.commit()

            rows = connection.execute(
                "select status,reason,updated_at from public.posting_status where "
                "posting_id = any(%s) order by posting_id", (LEGACY_IDS,),
            ).fetchall()
            assert [(row[0], row[1]) for row in rows] == [
                ("worth_checking", "saved verbatim"),
                ("not_relevant", "  ruled out verbatim  "),
                ("applied", "legacy stale reason"),
            ]
            assert [row[2] for row in rows] == [
                datetime(2001, 1, 1, tzinfo=timezone.utc),
                datetime(2002, 1, 1, tzinfo=timezone.utc),
                datetime(2003, 1, 1, tzinfo=timezone.utc),
            ]
            history_query = ("select company,role,application_date,outcome,recorded_at "
                             "from public.application_history")
            explicit_history = connection.execute(history_query).fetchall()
            assert explicit_history == [(
                "Explicit History Co", "Engineer", date(2020, 2, 3),
                "interviewed", datetime(2020, 2, 4, tzinfo=timezone.utc),
            )]
            assert connection.execute(
                "select column_name from information_schema.columns where "
                "table_schema='public' and table_name='application_history' "
                "order by ordinal_position"
            ).fetchall() == [(name,) for name in (
                "id", "posting_id", "company", "role", "application_date",
                "outcome", "recorded_at",
            )]
            assert connection.execute("select count(*) from public.posting_status_history").fetchone() == (0,)

            for field, value in profile_snapshot().items():
                if field not in {"people", "connectors"}:
                    connection.execute(
                        "insert into public.profile(field,value) values(%s,%s::jsonb) "
                        "on conflict(field) do update set value=excluded.value",
                        (field, json.dumps(value)),
                    )
            connection.execute(
                "insert into public.postings(id,source,external_id,url,title,company,raw_jd) "
                "values(%s,'capture','capture','https://example.test/capture',"
                "'Capture role','Capture Co',%s)", (CAPTURE_ID, "Full stack role. " * 20),
            )
            connection.execute("select public.set_status(%s,'new')", (CAPTURE_ID,))
            status_time = "select updated_at from public.posting_status where posting_id=%s"
            new_at = connection.execute(status_time, (CAPTURE_ID,)).fetchone()[0]
            before = persistence._capture(connection, CAPTURE_ID)
            connection.execute("update public.posting_status set status='seen' "
                               "where posting_id=%s and status='new'", (CAPTURE_ID,))
            seen_at = connection.execute(status_time, (CAPTURE_ID,)).fetchone()[0]
            after = persistence._capture(connection, CAPTURE_ID)
            assert after.history == before.history
            assert after.history_sha256 == before.history_sha256
            assert connection.execute(
                "select status_from,status_to,reason,recorded_at from "
                "public.posting_status_history where posting_id=%s order by recorded_at,id",
                (CAPTURE_ID,),
            ).fetchall() == [
                (None, "new", None, new_at),
                ("new", "seen", None, seen_at),
            ]
            assert connection.execute(history_query).fetchall() == explicit_history

            connection.execute(REGRESSION.read_text(encoding="utf-8"))
            connection.commit()
            assert connection.execute("select has_table_privilege('service_role',"
                "'public.posting_status_history','select,insert,update,delete,"
                "truncate,references,trigger')").fetchone() == (True,)
            connection.execute("set role anon")
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                connection.execute("select * from public.posting_status_history").fetchall()
            connection.rollback()
    except DatabaseUnavailable as error:
        pytest.skip(str(error))
