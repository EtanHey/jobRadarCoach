"""Durable regressions for PR #436 false-closure review findings."""
from urllib.error import HTTPError
import pytest
from scraper import liveness, recheck, database
from scraper.test_database import connection, migrated_database_url
URL = "https://www.linkedin.com/jobs/view/synthetic-engineer-1234567890"
GUEST = "https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/1234567890"
PHRASE = "No longer accepting applications"

class BoundedResponse:
    def __init__(self, url, body, status=200):
        self.url, self.body, self.status = url, body.encode(), status
    def __enter__(self): return self
    def __exit__(self, *_): pass
    def getcode(self): return self.status
    def geturl(self): return self.url
    def read(self, size): return self.body[:size]

def classify(body, url=GUEST):
    return liveness.check_url(url, guest_fallback=False,
        opener=lambda request, **_: BoundedResponse(request.full_url, body))

OPEN = '<main data-entity-urn="urn:li:jobPosting:1234567890"><h1>Synthetic Engineer</h1><a href="/apply">Apply</a></main>'
UNSAFE = {
    "hidden-template": OPEN + '<template><span>' + PHRASE + '</span></template>',
    "html-comment": OPEN + '<!-- <span>' + PHRASE + '</span> -->',
    "hidden-attribute": OPEN + '<div hidden>' + PHRASE + '</div>',
    "display-none": OPEN + '<div style="display:none">' + PHRASE + '</div>',
    "other-job-card": OPEN + '<aside><a href="/jobs/view/other-role-9999999999">Other job</a><span>' + PHRASE + '</span></aside>',
    "different-job-body": '<main data-entity-urn="urn:li:jobPosting:9999999999"><h1>Other job</h1><span>' + PHRASE + '</span></main>',
    "nested-login": '<h1><span>Sign in</span></h1><template><span>' + PHRASE + '</span></template>',
    "localized-login": '<title>LinkedIn: Anmelden</title><form action="/uas/login">Passwort</form><template><span>' + PHRASE + '</span></template>',
    "captcha-hidden-banner": '<h1>Security verification</h1><form id="captcha">Verify</form><template><span>' + PHRASE + '</span></template>',
    "consent-hidden-banner": '<h1>Consent required</h1><form id="consent">Agree</form><template><span>' + PHRASE + '</span></template>',
}
@pytest.mark.parametrize("name", UNSAFE)
def test_unrelated_or_nonvisible_text_never_closes_target(name):
    result = classify(UNSAFE[name])
    assert result["alive"] is None, (name, result)

@pytest.mark.parametrize("tag", ["script", "style"])
def test_capped_read_does_not_turn_code_into_visible_closure(tag):
    body = OPEN + '<' + tag + '>const message="' + PHRASE + '";' + "x" * 512000 + '</' + tag + '>'
    assert len(body.encode()) > 512000
    result = classify(body)
    assert result["alive"] is None, result

@pytest.mark.parametrize("phrase", [
    "No <span>longer</span> accepting applications",
    "Not <span>currently <em>accepting</em></span> applications",
    "NO&nbsp;LONGER&#32;ACCEPTING	APPLICATIONS",
    "Not\ncurrently&nbsp;accepting&#x20;applications",
])
@pytest.mark.parametrize("url", [URL, GUEST, "https://il.linkedin.com/jobs/view/synthetic-engineer-1234567890"])
def test_positive_controls(phrase, url):
    assert classify('<main data-entity-urn="urn:li:jobPosting:1234567890"><h1>Synthetic Engineer</h1><span class="topcard__flavor--closed">' + phrase + '</span></main>', url)["alive"] is False

@pytest.mark.parametrize("tag", ["script", "style"])
def test_complete_code_block_control(tag):
    assert classify(OPEN + '<' + tag + '>' + PHRASE + '</' + tag + '>')["alive"] is None

STATUS = '<span class="topcard__flavor--closed">' + PHRASE + '</span>'
TARGET = '<main data-entity-urn="urn:li:jobPosting:1234567890">'

@pytest.mark.parametrize("attribute", [
    'hidden', 'hidden="until-found"', 'aria-hidden="true"', 'inert',
    'style="display: none !important"', 'style="DISPLAY : NONE"',
    'style="visibility:hidden"', 'style="content-visibility:hidden"',
])
def test_hidden_status_ancestors_never_close_target(attribute):
    assert classify(TARGET + '<div ' + attribute + '>' + STATUS + '</div></main>')["alive"] is None

@pytest.mark.parametrize("body", [
    '<main>' + STATUS + '</main>',  # URL identity alone is insufficient.
    TARGET + '<p>' + PHRASE + '</p></main>',  # Description, not status.
    TARGET + '</main>' + STATUS,  # Status outside identified job.
    TARGET + '<aside>' + STATUS + '</aside></main>',  # Related card.
    TARGET + '<div data-entity-urn="urn:li:jobPosting:9999999999">' + STATUS + '</div></main>',
    '<main data-entity-urn="urn:li:jobPosting:9999999999">' + STATUS + '</main>' + TARGET + '</main>',
    TARGET + STATUS,  # Incomplete job region, even below byte cap.
    TARGET + '<span class="topcard__flavor--closed">' + PHRASE + '</main>',
    TARGET + '<template>' + STATUS + '</template></main>',
    TARGET + '<!-- ' + STATUS + ' --></main>',
    TARGET + '<script>' + PHRASE,  # Unclosed code below byte cap.
    TARGET + '<style>' + PHRASE,
    TARGET + STATUS + '</main>' + '<form action="/uas/login">Sign in</form>',
    TARGET + STATUS + '</main>' + '<form id="captcha">Verify</form>',
    TARGET + STATUS + '</main>' + '<form id="consent">Agree</form>',
])
def test_status_requires_complete_visible_target_job_region(body):
    assert classify(body)["alive"] is None

def test_closed_status_before_truncated_tail_is_still_unknown():
    assert classify(TARGET + STATUS + '</main>' + 'x' * 512000)["alive"] is None

def test_body_at_read_bound_is_unknown_without_assuming_eof():
    body = TARGET + STATUS + '</main>'
    assert classify(body + ' ' * (512000 - len(body.encode())))["alive"] is None

def test_unrelated_visible_phrase_does_not_replace_hidden_status():
    assert classify(TARGET + '<p>' + PHRASE + '</p><div hidden>' + STATUS + '</div></main>')["alive"] is None

def test_numeric_job_id_on_status_ancestor_is_supported():
    assert classify('<section data-job-id="1234567890">' + STATUS + '</section>')["alive"] is False

@pytest.mark.parametrize("limit,status", [(None,200), (120,200), (None,429)])
def test_actual_sql_row_cap_request_cap_and_spacing(connection, monkeypatch, limit, status):
    rows = [{"source":"linkedin", "id":str(8000000000+i), "title":"Synthetic Engineer",
             "company":"Synthetic", "url":f"https://www.linkedin.com/jobs/view/{8000000000+i}"}
            for i in range(125)]
    database.persist_postings(connection, rows, "2026-10-07T13:00:00Z")
    events=[]
    monkeypatch.setattr(recheck.time, "sleep", lambda delay: events.append(("sleep",delay)))
    def opener(request, **kwargs):
        events.append(("get",request.full_url))
        assert kwargs["timeout"] == 8
        if status == 429:
            raise HTTPError(request.full_url, 429, "synthetic", {}, None)
        return BoundedResponse(request.full_url, OPEN)
    monkeypatch.setattr(recheck, "pinned_open", opener)
    receipt = recheck.recheck(connection, scope="linkedin", **({} if limit is None else {"limit":limit}))
    expected = 60 if limit is None else limit
    assert receipt["checked"] == expected and receipt["unknown"] == expected
    gets=[value for kind,value in events if kind=="get"]
    assert len(gets) == expected * (2 if status==200 else 1)
    assert all(events[i]==("sleep",2.0) and events[i+1][0]=="get" for i in range(0,len(events),2))
    assert len(set(url for url in gets if "/jobs/view/" in url)) == expected
    attempted=connection.execute("select count(*) from postings where liveness ? 'last_attempt_at'").fetchone()[0]
    assert attempted == expected

def test_truncated_code_false_closure_persists_and_unknown_cannot_repair(connection, monkeypatch):
    body = OPEN + '<script>const message="' + PHRASE + '";' + "x"*512000 + '</script>'
    posting_id = database.persist_postings(connection,[{"source":"linkedin","id":"1234567890",
        "url":URL,"title":"Synthetic Engineer","company":"Synthetic"}],"2026-10-07T13:00:00Z")[0]
    monkeypatch.setattr(recheck.time, "sleep", lambda _:None)
    monkeypatch.setattr(recheck,"pinned_open",lambda request,**_:BoundedResponse(request.full_url,body))
    recheck.recheck(connection,scope="linkedin")
    stored=connection.execute("select liveness from postings where id=%s",(posting_id,)).fetchone()[0]
    recheck.recheck(connection,scope="linkedin",checker=lambda _:{"alive":None,"liveness_reason":"http-429-uncertain"})
    after=connection.execute("select liveness from postings where id=%s",(posting_id,)).fetchone()[0]
    assert "alive" not in stored and "alive" not in after, {"stored":stored,"after":after}
