"""Real, synthetic SQL verifies filtering before LIMIT and explicit override."""
from pathlib import Path
from uuid import uuid4
import json
import psycopg
import pytest
from test_support.postgres import migrated_database
from classifier.persistence import list_scoring_candidates
from classifier.test_core import profile_snapshot
from extractor.job import select_postings


@pytest.mark.parametrize('stage', ['extract', 'score'])
def test_gate_persists_before_selection_and_override_and_jd_reset(stage):
    with migrated_database(Path(__file__).parents[1]/'supabase/migrations', through=max(int(p.name[:4]) for p in (Path(__file__).parents[1]/'supabase/migrations').glob('[0-9][0-9][0-9][0-9]_*.sql'))) as url, psycopg.connect(url) as db:
        for field, value in profile_snapshot().items():
            if field not in {'people','connectors'}:
                db.execute('insert into profile(field,value) values(%s,%s::jsonb) on conflict(field) do update set value=excluded.value',(field,json.dumps(value)))
        ids=[str(uuid4()),str(uuid4())]
        for index,(id,title) in enumerate(zip(ids,['Principal Engineer','Frontend Engineer'])):
            db.execute("insert into postings(id,source,external_id,url,title,company,raw_jd,first_seen_at) values(%s,'synthetic',%s,'https://example.test/job',%s,'Synthetic',repeat('Build product applications with React and TypeScript. ',8),%s)",(id,id,title, '2020-01-01Z' if (index == 0) == (stage == 'extract') else '2021-01-01Z'))
            db.execute('insert into posting_status(posting_id) values(%s)',(id,))
        def selected(limit=1):
            if stage=='score':return list_scoring_candidates(db,limit=limit,posting_ids=ids)
            return [r['id'] for r in select_postings(db,limit=limit,posting_ids=ids)]
        assert selected(10)==[ids[1]]
        assert selected()==[ids[1]]
        assert db.execute('select relevance_filtered from postings where id=%s',(ids[0],)).fetchone()==(True,)
        assert db.execute("select relevance_gate->>'rule' from postings where id=%s",(ids[0],)).fetchone()==('leadership-title-strict',)
        db.execute("update postings set relevance_gate=relevance_gate || '{\"override\":true}'::jsonb where id=%s",(ids[0],))
        assert set((list_scoring_candidates(db,limit=10,posting_ids=ids) if stage=='score' else [r['id'] for r in select_postings(db,limit=10,posting_ids=ids)]))==set(ids)
        db.execute("update postings set title='Senior Frontend Engineer' where id=%s",(ids[0],))
        assert db.execute('select relevance_gate from postings where id=%s',(ids[0],)).fetchone()==({},)
        selected()
        assert db.execute('select relevance_filtered from postings where id=%s',(ids[0],)).fetchone()==(False,)


def test_explicit_us_rule_overrides_prior_score_but_preserves_other_history():
    from scraper.relevance import refresh_gate
    migrations=Path(__file__).parents[1]/'supabase/migrations'
    with migrated_database(migrations, through=28) as url, psycopg.connect(url) as db:
        ids=[str(uuid4()) for _ in range(3)]
        for id,title,status in zip(ids,['Full Stack Engineer','Principal Engineer','Full Stack Engineer'],['new','new','applied']):
            jd=('Applicants should already be based in United States. ' if title=='Full Stack Engineer' else '')+'Build React products. '*20
            db.execute("insert into postings(id,source,external_id,url,title,company,raw_jd) values(%s,'synthetic',%s,'https://example.test/job',%s,'Synthetic',%s)",(id,id,title,jd))
            db.execute('insert into posting_status(posting_id,status) values(%s,%s)',(id,status))
            payload=dict(employer_type="direct",seniority_real=None,fit_score=72,fit_tier="good",recommendation="apply",reasons=[],fit_line="",fit_line_evidence_ids=[],luna_status="ok")
            labels=dict(role_type=None,seniority_match="unknown",remote_ok="unknown",red_flag_count=0)
            db.execute("insert into posting_scores(posting_id,score,brain,model,scorer_version,posting_sha256,profile_sha256,history_sha256,score_payload,labels) values(%s,72,'synthetic','synthetic','1',%s,%s,%s,%s::jsonb,%s::jsonb)",(id,*(['a'*64]*3),json.dumps(payload),json.dumps(labels)))
        refresh_gate(db,posting_ids=ids)
        assert [db.execute('select relevance_filtered from postings where id=%s',(id,)).fetchone()[0] for id in ids]==[True,False,False]
        assert db.execute('select score from posting_scores where posting_id=%s',(ids[0],)).fetchone()==(72,)
