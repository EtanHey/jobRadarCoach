"""Real SQL vs the existing TS view, using only synthetic unique postings."""
import json
import os
import subprocess
import shutil
import socket
import time
from urllib.request import urlopen
from pathlib import Path
from uuid import UUID

import psycopg
import pytest
from psycopg.types.json import Jsonb

from test_support.postgres import DatabaseUnavailable, database_url, migrated_database

ROOT = Path(__file__).parents[1]


@pytest.fixture
def require_database():
    try:
        database_url()
    except DatabaseUnavailable as error:
        if os.environ.get("JOBRADAR_REQUIRE_PG17") == "1":
            pytest.fail(str(error))
        pytest.skip(str(error))


def test_board_filters_and_sorts_before_cap(tmp_path, require_database):
    rows = []
    for i in range(1012):
        score = None if i % 6 == 0 else i % 100
        recommendation = ["apply", "referral", "review", "skip"][i % 4] if score is not None else None
        rows.append(dict(id=str(UUID(int=i + 1)), title=f"Engineer {i:04}", company=f"Example {i}",
                         location=None, remote=None, seniority=[None, "Junior", "Senior", "Staff", "Director", "Intermediate", "Intern"][i % 7],
                         stack=[], salary=None, url=f"https://example.test/{i}", apply_url=None,
                         posted_at=None if i % 3 == 0 else "2026-09-01T00:00:00Z",
                         first_seen_at=f"2026-10-{1 + i % 5:02}T00:00:00Z", last_seen_at="2026-10-06T00:00:00Z",
                         source="synthetic", status=["new", "worth_checking", "applied"][i % 3],
                         status_reason=None, score=score, recommendation=recommendation, fit_line=None))
    # Old, highest-fit role is outside the newest 1,000; missing status means new.
    rows[0].update(location="Tel Aviv, Israel", work_mode="hybrid", seniority="Junior", score=100, recommendation="review", first_seen_at="2020-01-01T00:00:00Z")
    rows[1].update(score=99, posted_at="2026-09-01T00:00:00.000100Z")
    rows[2].update(score=99, posted_at="2026-09-01T00:00:00.000900Z")
    rows[7].update(seniority=None, title="Senior Engineer")
    for i in [15, 16]:
        rows[i].update(seniority="Junior", title="Equal title")
    base = dict(search="", source="", location="", seniority="", availability="all", statuses=[], fit="", sort="fit")
    cases = [{**base, "fit": fit, "sort": sort} for fit in ["", "recommended", "skip", "good", "scored", "unscored"]
             for sort in ["fit", "posted", "found", "seniority"]]
    cases.append({**base, "fit": "recommended", "statuses": ["worth_checking", "applied"]})
    expected = json.loads(subprocess.run(
        ["node", "--import", "tsx", "tests/fixtures/board-golden.ts"], cwd=ROOT / "ui",
        input=json.dumps(dict(rows=rows, cases=cases)), text=True, capture_output=True, check=True,
    ).stdout)
    assert expected[0][0] == rows[0]["id"]
    latest = max(int(p.name[:4]) for p in (ROOT / "supabase/migrations").glob("[0-9]*.sql"))
    with migrated_database(ROOT / "supabase/migrations", through=latest) as url, psycopg.connect(url) as db:
        for row in rows:
            db.execute("insert into postings(id,source,external_id,url,title,company,seniority,posted_at,first_seen_at,last_seen_at) "
                       "values (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                       tuple(row[k] for k in ["id", "source", "id", "url", "title", "company", "seniority", "posted_at", "first_seen_at", "last_seen_at"]))
            if row is not rows[0]:
                db.execute("insert into posting_status(status,posting_id) values (%s,%s)", (row["status"], row["id"]))
            else:
                db.execute("delete from posting_status where posting_id=%s", (row["id"],))
            if row["score"] is not None:
                reasons = [dict(factor="stack_domain_evidence", basis="posting", assessment="positive",
                                evidence_ids=["synthetic-1"], detail="Synthetic evidence. " * 25)] * 5
                payload = dict(employer_type="direct", seniority_real=None, fit_score=row["score"], fit_tier="good",
                               recommendation=row["recommendation"], reasons=reasons, fit_line="Synthetic fit", fit_line_evidence_ids=[], luna_status="ok")
                labels = dict(role_type=None, seniority_match="unknown", remote_ok="unknown", red_flag_count=0)
                db.execute("insert into posting_scores(posting_id,score,brain,model,scorer_version,posting_sha256,profile_sha256,history_sha256,score_payload,labels,reasons) "
                           "values (%s,%s,'synthetic','synthetic','1',%s,%s,%s,%s,%s,%s)",
                           (row["id"], row["score"], *(["a" * 64] * 3), Jsonb(payload), Jsonb(labels), Jsonb(reasons)))
        db.execute("update postings set location='Tel Aviv, Israel',work_mode='hybrid',work_mode_source='structured',seniority='Junior' where id=%s", (rows[0]["id"],))
        db.execute("set local role service_role")
        for case, ids in zip(cases, expected, strict=True):
            actual = db.execute("select id from public.board_postings('all','all',%s,%s,%s,1000)",
                                (case["fit"], case["statuses"], case["sort"])).fetchall()
            assert [str(row[0]) for row in actual] == ids, case
        assert db.execute("select id from board_postings('new-for-me','all','recommended','{}','fit',1000) limit 1").fetchone()[0] == UUID(rows[0]["id"])
        assert db.execute("select has_function_privilege('anon','public.board_postings(text,text,text,text[],text,integer,text,text,text,text,text,boolean)','execute')").fetchone() == (False,)
        # Opt-in real PostgREST/Supabase-client leg; SQL parity always runs in CI.
        if binary := os.environ.get("JOBRADAR_POSTGREST_BIN") or shutil.which("postgrest"):
            db.commit()
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                endpoint = f"http://127.0.0.1:{sock.getsockname()[1]}"
            with (tmp_path / "postgrest.log").open("w") as log, subprocess.Popen([binary], stdout=log, stderr=log, env={
                **os.environ, "PGRST_DB_URI": url, "PGRST_DB_SCHEMAS": "public", "PGRST_DB_ANON_ROLE": "service_role",
                "PGRST_SERVER_HOST": "127.0.0.1", "PGRST_SERVER_PORT": endpoint.rsplit(":", 1)[1], "PGRST_DB_CONFIG": "false", "GHCRTS": "-N2",
            }) as process:
                try:
                    for _ in range(100):
                        try:
                            with urlopen(endpoint, timeout=1):
                                break
                        except OSError:
                            if process.poll() is not None:
                                raise RuntimeError("Disposable PostgREST exited")
                            time.sleep(0.1)
                    else:
                        raise RuntimeError("Disposable PostgREST did not become ready")
                    result = subprocess.run(["node", "--conditions=react-server", "--import", "tsx", "tests/fixtures/board-http.ts"],
                                            cwd=ROOT / "ui", text=True, capture_output=True, timeout=60,
                                            env={**os.environ, "JOBRADAR_TEST_REST_URL": endpoint})
                    assert result.returncode == 0, result.stderr
                    assert json.loads(result.stdout) == dict(first=rows[0]["id"], count=1000, pipeline=True, window=True, poll=True, facets=True)
                finally:
                    process.terminate()
                    process.wait(timeout=10)
        else:
            assert os.environ.get("JOBRADAR_REQUIRE_LIST_DB") != "1", "PostgREST is required in CI"


@pytest.mark.parametrize("tie", ["discovery", "id"])
def test_unicode_equivalent_titles_at_board_cap(tie, require_database):
    # Exactly 999 titles precede the equivalent pair. Bytewise ordering must not
    # decide which member survives LIMIT instead of discovery time / ID.
    rows = [dict(id=str(UUID(int=i + 1)), title=f"A Engineer {i:04}",
                 company=f"Example {i}", seniority="Junior", source="synthetic",
                 first_seen_at="2026-10-01T00:00:00Z", posted_at=None, score=None,
                 status="new", location=None, remote=None, stack=[])
            for i in range(1003)]
    rows[999]["title"] = "e\u0301 Engineer" if tie == "discovery" else "\u00e9 Engineer"
    rows[1000]["title"] = "\u00e9 Engineer" if tie == "discovery" else "e\u0301 Engineer"
    if tie == "discovery":
        rows[1000]["first_seen_at"] = "2026-10-02T00:00:00Z"
    for row in rows[1001:]:
        row["title"] = "Z Engineer"
    case = dict(search="", source="", location="", seniority="", availability="all",
                statuses=[], fit="", sort="seniority")
    expected = json.loads(subprocess.run(
        ["node", "--import", "tsx", "tests/fixtures/board-golden.ts"], cwd=ROOT / "ui",
        input=json.dumps(dict(rows=rows, cases=[case])), text=True, capture_output=True, check=True,
    ).stdout)[0]
    assert expected[-1] == rows[1000 if tie == "discovery" else 999]["id"]
    latest = max(int(p.name[:4]) for p in (ROOT / "supabase/migrations").glob("[0-9]*.sql"))
    with migrated_database(ROOT / "supabase/migrations", through=latest) as url, psycopg.connect(url) as db:
        for row in rows:
            db.execute("insert into postings(id,source,external_id,url,title,company,seniority,first_seen_at,last_seen_at) "
                       "values (%s,'synthetic',%s,'https://example.test',%s,%s,'Junior',%s,'2026-10-06')",
                       (row["id"], row["id"], row["title"], row["company"], row["first_seen_at"]))
        db.execute("set local role service_role")
        actual = db.execute("select id from public.board_postings('all','all','','{}','seniority',1000)").fetchall()
        assert [str(row[0]) for row in actual] == expected
