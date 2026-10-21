"""Location blocking applies before the board cap, using existing score JSON."""

import json
from pathlib import Path
from uuid import uuid4

import psycopg

from test_support.postgres import migrated_database
from scraper.test_annotate import structured_annotation


def test_recommended_excludes_blocked_before_limit():
    migrations = Path(__file__).parents[1] / "supabase/migrations"
    through = max(
        int(p.name[:4]) for p in migrations.glob("[0-9][0-9][0-9][0-9]_*.sql")
    )
    with (
        migrated_database(migrations, through=through) as url,
        psycopg.connect(url) as db,
    ):
        expected = []
        for index, eligibility in enumerate(["blocked", "eligible", "unknown", None]):
            ident = str(uuid4())
            db.execute(
                "insert into postings(id,source,external_id,url,title,company) values(%s,'synthetic',%s,'https://example.test/job','Engineer','Example')",
                (ident, ident),
            )
            payload = {
                **structured_annotation(ident, fit_score=99 - index),
                "luna_status": "ok",
            }
            if eligibility:
                payload["eligibility"] = eligibility
                payload["eligibility_reason"] = '"Synthetic location evidence"'
            db.execute(
                "insert into posting_scores(posting_id,score,reasons,labels,brain,model,scorer_version,posting_sha256,profile_sha256,history_sha256,score_payload) values(%s,%s,%s::jsonb,%s::jsonb,'ollama','test','1.1',%s,%s,%s,%s::jsonb)",
                (
                    ident,
                    99 - index,
                    json.dumps(payload["reasons"]),
                    json.dumps(
                        {
                            "role_type": None,
                            "seniority_match": "unknown",
                            "remote_ok": "unknown",
                            "red_flag_count": 0,
                        }
                    ),
                    *("0" * 64,) * 3,
                    json.dumps(payload),
                ),
            )
            if eligibility != "blocked":
                expected.append((ident,))
        assert (
            db.execute(
                "select id::text from board_postings('all','all','recommended','{}','fit',1)"
            ).fetchall()
            == expected[:1]
        )
        assert (
            db.execute(
                "select id::text from board_postings('all','all','recommended','{}','fit',1000)"
            ).fetchall()
            == expected
        )
        assert db.execute(
            "select count(*) from board_postings('all','all','good')"
        ).fetchone() == (4,)
