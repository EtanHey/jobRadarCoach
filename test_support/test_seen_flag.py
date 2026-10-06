from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from test_support.postgres import DatabaseUnavailable, migrated_database


ROOT = Path(__file__).parents[1]
MIGRATIONS = ROOT / "supabase/migrations"
MIGRATION = MIGRATIONS / "0013_seen_flag.sql"
IDS = [f"00000000-0000-0000-0000-{number}" for number in (
    "000000013001", "000000013002", "000000013003", "000000013004",
    "000000013005", "000000013006",
)]


def test_seen_flag_contract() -> None:
    try:
        database = migrated_database(MIGRATIONS, through=12)
        with database as url, psycopg.connect(url) as connection:
            for number, posting_id in enumerate(IDS, 1):
                connection.execute(
                    "insert into public.postings "
                    "(id,source,external_id,url,title,company) values "
                    "(%s,'seen-flag',%s,%s,%s,'Seen Flag Co')",
                    (posting_id, f"seen-{number}",
                     f"https://example.test/seen-{number}", f"Role {number}"),
                )
            connection.execute(
                "insert into public.posting_status(posting_id,status,updated_at) values "
                "(%s,'new','2001-01-01Z'),(%s,'seen','2002-01-01Z'),"
                "(%s,'applied','2003-01-01Z')", IDS[:3],
            )
            connection.commit()
            legacy_times = connection.execute(
                "select updated_at from public.posting_status "
                "where posting_id=any(%s) order by posting_id", (IDS[:3],),
            ).fetchall()
            connection.execute(MIGRATION.read_text(encoding="utf-8"))
            connection.commit()

            rows = connection.execute(
                "select status,seen,seen_at from public.posting_status "
                "where posting_id=any(%s) order by posting_id", (IDS[:3],),
            ).fetchall()
            assert rows == [
                ("new", False, None),
                ("seen", True, legacy_times[1][0]),
                ("applied", True, legacy_times[2][0]),
            ]

            # Board auto-seen conflict-ignore upsert plus legacy raw update.
            connection.execute(
                "insert into public.posting_status(posting_id,status) values(%s,'new')",
                (IDS[3],),
            )
            connection.execute(
                "insert into public.posting_status(posting_id,status) values(%s,'seen') "
                "on conflict(posting_id) do nothing", (IDS[3],),
            )
            connection.execute(
                "update public.posting_status set status='seen',reason=null "
                "where posting_id=%s and status='new'", (IDS[3],),
            )
            assert connection.execute(
                "select status,seen,seen_at is not null from public.posting_status "
                "where posting_id=%s", (IDS[3],),
            ).fetchone() == ("seen", True, True)

            # New flag-only writes map back to the legacy phase-A status.
            connection.execute("update public.posting_status set seen=false where posting_id=%s", (IDS[3],))
            assert connection.execute(
                "select status,seen,seen_at from public.posting_status where posting_id=%s",
                (IDS[3],),
            ).fetchone() == ("new", False, None)
            connection.execute("update public.posting_status set seen=true where posting_id=%s", (IDS[3],))
            assert connection.execute(
                "select status,seen from public.posting_status where posting_id=%s", (IDS[3],),
            ).fetchone() == ("seen", True)

            applied_before = connection.execute(
                "select status,reason,updated_at,seen,seen_at from public.posting_status "
                "where posting_id=%s", (IDS[2],),
            ).fetchone()
            history_before = connection.execute(
                "select count(*) from public.posting_status_history where posting_id=%s",
                (IDS[2],),
            ).fetchone()
            connection.execute("select public.mark_seen(%s)", (IDS[2],))
            assert connection.execute(
                "select status,reason,updated_at,seen,seen_at from public.mark_seen(%s)",
                (IDS[2],),
            ).fetchone() == applied_before
            assert connection.execute(
                "select count(*) from public.posting_status_history where posting_id=%s",
                (IDS[2],),
            ).fetchone() == history_before
            assert connection.execute(
                "select status,seen,seen_at is not null from public.mark_seen(%s)",
                (IDS[4],),
            ).fetchone() == ("seen", True, True)
            changed = connection.execute(
                "select status,seen from public.set_status(%s,'skipped')", (IDS[3],),
            ).fetchone()
            assert changed == ("skipped", True)
            assert connection.execute(
                "select status_from,status_to from public.posting_status_history "
                "where posting_id=%s order by recorded_at desc,id desc limit 1", (IDS[3],),
            ).fetchone() == ("seen", "skipped")

            assert connection.execute(
                "select count(*) from public.posting_status "
                "where seen is distinct from (status <> 'new')"
            ).fetchone() == (0,)

            for routine in (
                "mark_seen(uuid)",
            ):
                assert connection.execute(
                    "select not has_function_privilege('anon',%s,'execute') and "
                    "not has_function_privilege('authenticated',%s,'execute') and "
                    "has_function_privilege('service_role',%s,'execute') and "
                    "not has_function_privilege('public',%s,'execute')",
                    tuple(f"public.{routine}" for _ in range(4)),
                ).fetchone() == (True,)
    except DatabaseUnavailable as error:
        pytest.skip(str(error))
