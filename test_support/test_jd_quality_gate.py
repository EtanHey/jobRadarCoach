"""Synthetic database acceptance; CI supplies PostgreSQL (no Docker setup here)."""
import json

import pytest

from scraper.relevance import refresh_gate
from scraper.test_jd_quality import MIXED, TEMPLATE, EXTERNAL
from test_support.test_cloud_relevance_gate import db, observation, write


@pytest.mark.parametrize("jd,reason", [
    (None, "missing-body"), (TEMPLATE, "unfilled-template"),
    (MIXED, "mixed-role"), (EXTERNAL, "external-summary"),
])
@pytest.mark.parametrize("scored", [False, True])
def test_quality_withholds_current_advice_and_recovers_after_repair(db, jd, reason, scored):
    [pid] = write(db, observation("Frontend Engineer"))["inserted_posting_ids"]
    if scored:
        payload = dict(employer_type="direct", seniority_real=None, fit_score=72,
                       fit_tier="good", recommendation="apply", reasons=[],
                       fit_line="", fit_line_evidence_ids=[], luna_status="ok")
        labels = dict(role_type=None, seniority_match="unknown", remote_ok="unknown", red_flag_count=0)
        db.execute("insert into posting_scores(posting_id,score,brain,model,scorer_version,posting_sha256,"
                   "profile_sha256,history_sha256,score_payload,labels) values"
                   "(%s,72,'synthetic','synthetic','1',%s,%s,%s,%s::jsonb,%s::jsonb)",
                   (pid, *(["a" * 64] * 3), json.dumps(payload), json.dumps(labels)))
    db.execute("update postings set raw_jd=%s where id=%s", (jd, pid))
    refresh_gate(db, posting_ids=[pid])
    assert db.execute("select relevance_filtered,relevance_gate->>'rule' from postings where id=%s",
                      (pid,)).fetchone() == (True, f"jd-quality-{reason}")
    assert not db.execute("select id from board_postings(filter=>'all') where id=%s", (pid,)).fetchall()
    assert db.execute("select id from board_postings(filter=>'not-scored') where id=%s", (pid,)).fetchone()
    db.execute("update postings set raw_jd=%s where id=%s", (observation()["jd_text"], pid))
    refresh_gate(db, posting_ids=[pid])
    assert db.execute("select relevance_filtered from postings where id=%s", (pid,)).fetchone() == (False,)
