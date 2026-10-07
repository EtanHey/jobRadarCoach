"""Provider-captured controls and r1/r2 false-closure regressions."""
from pathlib import Path
from urllib.error import HTTPError, URLError
import pytest
from scraper import liveness, recheck, database
from scraper.test_database import connection, migrated_database_url

URL = 'https://il.linkedin.com/jobs/view/synthetic-engineer-1234567890'
GUEST = 'https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/1234567890'
PHRASE = 'No longer accepting applications'
STATUS = '<figure class="closed-job"><figcaption class="closed-job__flavor--closed">'+PHRASE+'</figcaption></figure>'
TOP = '<section class="top-card-layout">'
CLOSED = TOP+STATUS+'</section>'
OPEN = '<main data-entity-urn="urn:li:jobPosting:1234567890"><a href="/apply">Apply</a></main>'

class Response:
    def __init__(self, url, body, status=200):
        self.url, self.body, self.status = url, body.encode(), status
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def getcode(self): return self.status
    def geturl(self): return self.url
    def read(self, size): return self.body[:size]

def classify(body, url=GUEST):
    return liveness.check_url(url, opener=lambda request, **_: Response(request.full_url, body))

@pytest.mark.parametrize('job_id,closed', [('4469662667',True),('4476383841',True),('4462954347',False),('4461128829',False)])
def test_real_guest_capture(job_id, closed):
    body=(Path(__file__).parent/'fixtures/linkedin-guest'/f'{job_id}-2026-10-07.html').read_text()
    result=classify(body, f'https://www.linkedin.com/jobs/view/{job_id}')
    assert result['alive'] is None
    assert bool(result.get('linkedin_closed_signal')) is closed
    assert result['liveness_final_url'] == f'https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{job_id}'
    if closed:
        assert result['linkedin_closed_signal']['phrase']=='no longer accepting applications'
        assert result['liveness_checked_at'].endswith('Z')

@pytest.mark.parametrize('phrase', ['No <span>longer</span> accepting applications',
    'Not <span>currently <em>accepting</em></span> applications',
    'NO&nbsp;LONGER&#32;ACCEPTING\tAPPLICATIONS','Not\ncurrently&nbsp;accepting&#x20;applications'])
@pytest.mark.parametrize('url', [URL,GUEST,'https://www.linkedin.com/jobs/view/1234567890'])
def test_synthetic_visible_phrase_controls(phrase, url):
    result = classify(CLOSED.replace(PHRASE,phrase),url)
    assert result['alive'] is None
    assert result['linkedin_closed_signal']['url'] == url
    assert result['linkedin_closed_signal']['checked_at'].endswith('Z')

@pytest.mark.parametrize('wrapper', ['<template>{}</template>','<!-- {} -->','<script>{}</script>',
    '<style>{}</style>','<div hidden>{}</div>','<div hidden="until-found">{}</div>',
    '<div aria-hidden="true">{}</div>','<div inert>{}</div>',
    '<div style="display:none">{}</div>','<div style="DISPLAY : NONE">{}</div>',
    '<div style="display:none!important">{}</div>','<div style="visibility:hidden">{}</div>',
    '<div style="content-visibility:hidden">{}</div>','<div style="display:/**/none">{}</div>',
    '<div style="display:none/**/">{}</div>','<div style="visibility:/**/hidden">{}</div>',
    '<div style="dis\\70lay:none">{}</div>','<aside>{}</aside>','<nav>{}</nav>','<footer>{}</footer>',
    '<a href="/jobs/view/9999999999">Other job{}</a>',
    '<div data-entity-urn="urn:li:jobPosting:9999999999">{}</div>',
    '<div data-job-id="9999999999">{}</div>'])
def test_hidden_or_foreign_status_never_closes(wrapper):
    assert classify(TOP+wrapper.format(STATUS)+'</section>')['alive'] is None

@pytest.mark.parametrize('body', [OPEN+'<template>'+PHRASE+'</template>',
    OPEN+'<!-- <span>'+PHRASE+'</span> -->',OPEN+'<div hidden>'+PHRASE+'</div>',
    OPEN+'<div style="display:none">'+PHRASE+'</div>',
    OPEN+'<aside><a href="/jobs/view/9999999999">'+PHRASE+'</a></aside>',
    '<main data-entity-urn="urn:li:jobPosting:9999999999">'+PHRASE+'</main>',
    '<h1><span>Sign in</span></h1><template>'+PHRASE+'</template>',
    '<title>LinkedIn: Anmelden</title><form action="/uas/login"><template>'+PHRASE+'</template></form>',
    '<h1>Security verification</h1><form id="captcha"><template>'+PHRASE+'</template></form>',
    '<h1>Consent required</h1><form id="consent"><template>'+PHRASE+'</template></form>',
    TOP+'<p>'+PHRASE+'</p></section>',TOP+'</section>'+STATUS,TOP+STATUS,
    CLOSED+'<form action="/uas/login">Sign in</form>',CLOSED+'<form id="captcha">Verify</form>',
    CLOSED+'<form id="consent">Agree</form>', '<html><body>'+CLOSED+'</body></html>',
    CLOSED+CLOSED, CLOSED+'<aside>'+STATUS+'</aside>',
    TOP+'<style>.closed-job {display:none}</style>'+STATUS+'</section>',
    CLOSED.replace(PHRASE,'<template>'+PHRASE+'</template>'),
    CLOSED.replace(PHRASE,'<svg><title>'+PHRASE+'</title></svg>'),
    CLOSED.replace(PHRASE,'<svg><desc>'+PHRASE+'</desc></svg>'),
    CLOSED.replace(PHRASE,'<!-- '+PHRASE+' -->'),
    TOP+'<figcaption class="closed-job__flavor--closed">'+PHRASE+'</figcaption></section>',
    TOP+'<span class="topcard__flavor--closed">'+PHRASE+'</span></section>',
    CLOSED.replace('</figcaption>',''),CLOSED+'<script>'+PHRASE,CLOSED+'<style>'+PHRASE])
def test_nonfragment_or_unowned_status_unknown(body):
    assert classify(body)['alive'] is None

@pytest.mark.parametrize('tag', ['script','style'])
def test_bounded_or_incomplete_body_is_unknown(tag):
    assert classify(OPEN+f'<{tag}>'+PHRASE+'x'*512000+f'</{tag}>')['alive'] is None
    assert classify(CLOSED+'x'*512000)['alive'] is None

@pytest.mark.parametrize('status',[302,404,410,429,500,503])
@pytest.mark.parametrize('raised',[True,False])
def test_http_failure_has_one_guest_request_and_no_closure(status,raised):
    calls=[]
    def opener(request,**_):
        calls.append(request.full_url)
        if raised: raise HTTPError(request.full_url,status,'synthetic',{},None)
        return Response(request.full_url,CLOSED,status)
    assert liveness.check_url(URL,opener=opener)['alive'] is None
    assert calls==[GUEST]

@pytest.mark.parametrize('final',['https://www.linkedin.com/authwall','https://www.linkedin.com/jobs/search/',
    'https://www.linkedin.com/jobs/view/9999999999',GUEST+'?redirected=1'])
def test_any_redirect_unknown(final):
    assert liveness.check_url(URL,opener=lambda *_a,**_k:Response(final,CLOSED))['alive'] is None

def test_hidden_guest_sign_in_modal_is_not_a_login_wall():
    body=CLOSED.replace('</section>','<form class="contextual-sign-in-modal__sign-in-form hidden" action="/uas/login-submit"></form></section>')
    assert classify(body)['alive'] is None
    assert classify(body).get('linkedin_closed_signal')

def test_bare_attributes_in_real_markup_do_not_crash():
    body=CLOSED+'<div class="decorated-job-posting__details"><div class aria-hidden href>Details</div></div>'
    assert classify(body)['alive'] is None
    assert classify(body).get('linkedin_closed_signal')

def test_network_failure_not_retried():
    calls=[]
    def opener(request,**_):
        calls.append(request.full_url); raise URLError('offline')
    assert liveness.check_url(URL,opener=opener)['alive'] is None
    assert calls==[GUEST]

def test_harvest_guest_request_preserves_single_call_budget(monkeypatch):
    original=liveness.check_url; calls=[]
    monkeypatch.setattr(liveness,'check_url',lambda url:original(url,opener=lambda r,**_:calls.append(r.full_url) or Response(r.full_url,CLOSED)))
    result=liveness.check_posting({'url':URL})
    assert calls==[GUEST]
    assert database._liveness_evidence({'source':'linkedin','url':URL,**result})['linkedin_closed_signal']['phrase']=='no longer accepting applications'

@pytest.mark.parametrize('limit,status',[(60,200),(120,200),(60,429)])
def test_real_sql_rotates_capped_rows_and_paces_single_get(connection,monkeypatch,limit,status):
    rows=[{'source':'linkedin','id':str(8000000000+i),'title':'Synthetic Engineer','company':'Synthetic',
        'url':f'https://www.linkedin.com/jobs/view/{8000000000+i}'} for i in range(125)]
    database.persist_postings(connection,rows,'2026-10-07T13:00:00Z'); events=[]
    monkeypatch.setattr(recheck.time,'sleep',lambda delay:events.append(delay))
    def opener(request,**kwargs):
        events.append(request.full_url); assert kwargs['timeout']==8
        return Response(request.full_url,TOP+'</section>',status)
    monkeypatch.setattr(recheck,'pinned_open',opener)
    assert recheck.recheck(connection,limit=limit,scope='linkedin')['checked']==limit
    assert len(events)==2*limit
    assert all(events[i]==2.0 and '/jobs-guest/' in events[i+1] for i in range(0,len(events),2))
    first=set(connection.execute("select id from postings where liveness ? 'last_attempt_at'").fetchall())
    recheck.recheck(connection,limit=5,scope='linkedin')
    second=set(connection.execute("select id from postings where liveness ? 'last_attempt_at'").fetchall())
    assert len(second-first)==5

@pytest.mark.parametrize('unsafe_body',[CLOSED.replace(STATUS,'<div style="display:/**/none">'+STATUS+'</div>'),
    CLOSED+'x'*512000,TOP+'<a href="/jobs/view/9999999999">'+STATUS+'</a></section>',
    CLOSED.replace(PHRASE,'<svg><title>'+PHRASE+'</title></svg>')])
def test_real_sql_hidden_status_and_unknown_preserve_prior_closure(connection,monkeypatch,unsafe_body):
    posting_id=database.persist_postings(connection,[{'source':'linkedin','id':'1234567890',
        'title':'Engineer','company':'Synthetic','url':URL}],'2026-10-07T13:00:00Z')[0]
    monkeypatch.setattr(recheck.time,'sleep',lambda _:None)
    body=unsafe_body
    monkeypatch.setattr(recheck,'pinned_open',lambda r,**_:Response(r.full_url,body))
    assert recheck.recheck(connection,scope='linkedin')['unknown']==1
    assert 'alive' not in connection.execute('select liveness from postings where id=%s',(posting_id,)).fetchone()[0]
    body=CLOSED
    assert recheck.recheck(connection,scope='linkedin')['closed']==0
    before=connection.execute('select liveness from postings where id=%s',(posting_id,)).fetchone()[0]
    body=CLOSED+'x'*512000
    assert recheck.recheck(connection,scope='linkedin')['unknown']==1
    after=connection.execute('select liveness from postings where id=%s',(posting_id,)).fetchone()[0]
    assert 'alive' not in after
    assert after['linkedin_closed_signal']==before['linkedin_closed_signal']
