from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest
from psycopg.rows import dict_row

from scripts.job_api_contract import write_contract
from test_support.postgres import DatabaseUnavailable, migrated_database

ROOT = Path(__file__).parents[1]
MIGRATIONS = ROOT / "supabase/migrations"
SNAPSHOT = ROOT / "supabase/contracts/job_api.json"
IDS = [f"00000000-0000-0000-0000-00000001400{number}" for number in range(1, 6)]

def _seed(connection: psycopg.Connection) -> None:
    connection.execute(
        """insert into public.postings
          (id, source, external_id, url, title, company, location, remote, seniority, stack, salary, apply_url, posted_at, first_seen_at)
        values
          (%s, 'fixture', 'one', 'https://example.test/one', 'Senior Python Engineer', 'Acme', 'Tel Aviv, Israel', true, 'Senior', array['Python','PostgreSQL'], '$100k', 'https://apply.workable.com/acme/jobs/view/ABC123.md', '2026-09-10 10:00Z', '2026-09-10 10:00Z'),
          (%s, 'fixture', 'two', 'https://example.test/two', 'Backend Engineer', 'Beta', 'Remote - Israel', false, 'Mid', array['Python'], null, 'https://example.test/apply/two', '2026-09-09 10:00Z', '2026-09-09 10:00Z'),
          (%s, 'fixture', 'three', 'https://example.test/three', 'Platform Engineer', 'Gamma', 'Haifa', true, 'Senior', array['Go'], null, '', '2026-09-08 10:00Z', '2026-09-08 10:00Z'),
          (%s, 'fixture', 'four', 'https://example.test/four', 'Junior Engineer', 'Delta', 'Jerusalem', null, 'Junior', array['Ruby'], null, null, '2026-09-07 10:00Z'),
          (%s, 'fixture', 'five', 'https://example.test/five', 'Unscored Engineer', 'Epsilon', 'Tel Aviv', true, 'Senior', array['Rust'], null, null, '2026-09-06 10:00Z')""",
        IDS,
    )
    payload = {"employer_type": "unknown", "seniority_real": None, "fit_score": 95, "fit_tier": "strong", "recommendation": "review", "reasons": [], "fit_line": "fixture", "fit_line_evidence_ids": [], "luna_status": "ok"}
    connection.execute(
        """insert into public.posting_scores
          (posting_id, score, reasons, labels, brain, model, scorer_version, posting_sha256, profile_sha256, history_sha256, score_payload)
        values
          (%s, 95, '[]', '{"role_type":null,"seniority_match":"unknown","remote_ok":"unknown","red_flag_count":0}', 'test', 'test-model', 'test-1', repeat('a', 64), repeat('b', 64), repeat('c', 64), %s),
          (%s, 69, '[]', '{"role_type":null,"seniority_match":"unknown","remote_ok":"unknown","red_flag_count":0}', 'test', 'test-model', 'test-1', repeat('a', 64), repeat('b', 64), repeat('c', 64), %s),
          (%s, 39, '[]', '{"role_type":null,"seniority_match":"unknown","remote_ok":"unknown","red_flag_count":0}', 'test', 'test-model', 'test-1', repeat('a', 64), repeat('b', 64), repeat('c', 64), %s)""",
        (IDS[0], json.dumps(payload), IDS[1], json.dumps({**payload, "fit_score": 69, "fit_tier": "stretch"}), IDS[2], json.dumps({**payload, "fit_score": 39, "fit_tier": "weak"})),
    )
    connection.execute("insert into public.posting_status(posting_id,status) values (%s,'applied'),(%s,'seen')", (IDS[0], IDS[1]))
    connection.execute(
        """insert into public.posting_extractions
          (posting_id, brain, model, extractor_version, schema_sha256, jd_sha256, fingerprint, facts)
        values (%s, 'test', 'test-model', 'test-1', repeat('a',64), repeat('b',64), repeat('c',64), %s)""",
        (IDS[0], json.dumps({"location": {"value": None, "evidence_quote": None}, "remote": {"value": None, "evidence_quote": None}, "seniority": {"value": None, "evidence_quote": None}, "stack": [], "salary": {"value": None, "evidence_quote": None}})),
    )
    connection.commit()

def _rows(connection: psycopg.Connection, function: str, arguments: tuple[object, ...]) -> list[dict[str, object]]:
    return connection.execute(f"select * from public.{function}({', '.join(['%s'] * len(arguments))})", arguments).fetchall()

def _ids(rows: list[dict[str, object]]) -> list[str]:
    return [str(row["id"]) for row in rows]

def test_job_api_contract_snapshot_matches_migrated_database(tmp_path: Path) -> None:
    try:
        database = migrated_database(MIGRATIONS, through=14)
        with database as url, psycopg.connect(url) as connection:
            generated = tmp_path / "job_api.json"
            write_contract(connection, generated)
            assert generated.read_text(encoding="utf-8") == SNAPSHOT.read_text(encoding="utf-8")
    except DatabaseUnavailable as error:
        pytest.skip(str(error))

def test_job_api_search_count_detail_and_security_contract() -> None:
    try:
        database = migrated_database(MIGRATIONS, through=14)
        with database as url, psycopg.connect(url, row_factory=dict_row) as connection:
            _seed(connection)
            assert connection.execute("select array[public.score_band(%s),public.score_band(%s),public.score_band(%s),public.score_band(%s),public.score_band(%s),public.score_band(%s),public.score_band(%s)] bands", (None, 0, 39, 40, 69, 70, 100)).fetchone()["bands"] == [None, "below", "below", "more", "more", "strong", "strong"]
            search_args = (False, 0, None, None, "engineer", None, [], False, 20)
            search_rows = _rows(connection, "search_jobs", search_args)
            list_rows = connection.execute("select * from public.list_jobs(false,20,0,null,null,'engineer')").fetchall()
            assert [row["id"] for row in search_rows] == [row["posting_id"] for row in list_rows]
            cards = _rows(connection, "search_jobs", (None, None, None, None, None, None, [], False, 20))
            assert _ids(cards) == IDS
            cards_by_id = {str(row["id"]): row for row in cards}
            assert cards_by_id[IDS[2]]["apply_url"] == "https://example.test/three"
            assert cards_by_id[IDS[3]]["apply_url"] == "https://example.test/four"
            assert _ids(_rows(connection, "search_jobs", (None, None, None, None, None, True, [], False, 20))) == [IDS[0], IDS[2], IDS[4]]
            assert _ids(_rows(connection, "search_jobs", (None, None, None, None, None, None, [IDS[0]], False, 20))) == [IDS[1], IDS[2], IDS[3], IDS[4]]
            assert _ids(_rows(connection, "search_jobs", (None, None, None, None, None, None, [], True, 20))) == [IDS[0], IDS[1], IDS[2]]
            assert len(_rows(connection, "search_jobs", (False, None, None, None, None, None, [], False, 1))) == 1
            for value in (0, 1001):
                with pytest.raises(psycopg.errors.InvalidParameterValue):
                    _rows(connection, "search_jobs", (False, None, None, None, None, None, [], False, value))
                connection.rollback()
            counts = connection.execute("select * from public.count_jobs(null,null,null,null,null,null,'{}',false)").fetchone()
            assert counts == {"strong": 1, "more": 1, "below": 1, "unscored": 2}
            assert connection.execute("select strong + more + below + unscored total from public.count_jobs(null,40,null,null,null,null,'{}',false)").fetchone()["total"] == 2
            before = connection.execute("select status,seen,seen_at,updated_at from public.posting_status where posting_id=%s", (IDS[0],)).fetchone()
            history_before = connection.execute("select count(*) from public.posting_status_history where posting_id=%s", (IDS[0],)).fetchone()
            detail = _rows(connection, "get_job", (IDS[0],))[0]
            assert str(detail["id"]) == IDS[0] and detail["apply_url"] == "https://apply.workable.com/acme/j/ABC123/" and detail["link_url"] == detail["apply_url"]
            assert detail["extraction_state"] == "extracted" and detail["score_band"] == "strong" and detail["fit_tier"] == "strong"
            assert connection.execute("select status,seen,seen_at,updated_at from public.posting_status where posting_id=%s", (IDS[0],)).fetchone() == before
            assert connection.execute("select count(*) from public.posting_status_history where posting_id=%s", (IDS[0],)).fetchone() == history_before
            assert _rows(connection, "get_job", ("00000000-0000-0000-0000-000000014099",)) == []
            assert connection.execute("select array[public.job_link_url(%s,%s),public.job_link_url(%s,%s),public.job_link_url(%s,%s)] links", ("https://apply.workable.com/acme/jobs/view/AbC123.md", "https://fallback.test", "", "https://fallback.test/job", "https://other.test/jobs/view/AbC123.md", "https://ignored.test")).fetchone()["links"] == ["https://apply.workable.com/acme/j/AbC123/", "https://fallback.test/job", "https://other.test/jobs/view/AbC123.md"]
            status_values = (None, "", "https://example.test/job", "ftp://example.test/job", "https://user@example.test/job", "https://[not-an-ip]/job", "https://[2001:db8::1]/job", "https://example.test:0/job", "https://example.test:65535/job", "https://example.test:65536/job", "https:///job")
            assert connection.execute("select array[" + ",".join(["public.job_link_status(%s)"] * len(status_values)) + "] statuses", status_values).fetchone()["statuses"] == ["no_link", "no_link", "available", "invalid_url", "invalid_url", "invalid_url", "available", "available", "available", "invalid_url", "invalid_url"]
            routines = ("score_band(smallint)", "job_link_url(text,text)", "job_link_status(text)", "search_jobs(boolean,integer,text,text,text,boolean,uuid[],boolean,integer)", "count_jobs(boolean,integer,text,text,text,boolean,uuid[],boolean)", "get_job(uuid)")
            for routine in routines:
                assert connection.execute("select not has_function_privilege('anon',%s,'execute') and not has_function_privilege('authenticated',%s,'execute') and has_function_privilege('service_role',%s,'execute') and not has_function_privilege('public',%s,'execute')", tuple(f"public.{routine}" for _ in range(4))).fetchone()["?column?"] is True
    except DatabaseUnavailable as error:
        pytest.skip(str(error))
