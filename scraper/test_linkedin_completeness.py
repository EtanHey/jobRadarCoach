"""Native rendering, normalized ownership and real HTTP framing regressions."""
from io import BytesIO
import http.client
from urllib.request import HTTPSHandler, build_opener

import pytest

from scraper import database, liveness, recheck
from scraper.public_https import _Response
from scraper.test_database import connection, migrated_database_url
from scraper.test_linkedin_guest import CLOSED, GUEST, STATUS, TOP, URL, Response, classify


HIDDEN = ['<dialog>{}</dialog>', '<details><summary>Other</summary>{}</details>',
          '<div popover>{}</div>', '<div popover="manual">{}</div>',
          '<details><summary>Other</summary><summary>{}</summary></details>',
          '<details><div><summary>{}</summary></div></details>',
          '<textarea>{}</textarea>', '<select>{}</select>', '<iframe>{}</iframe>',
          '<object>{}</object>']


@pytest.mark.parametrize('wrapper', HIDDEN)
def test_native_nonrendered_status_unknown(wrapper):
    assert classify(TOP + wrapper.format(STATUS) + '</section>')['alive'] is None


@pytest.mark.parametrize('wrapper', ['<dialog open>{}</dialog>', '<details open>{}</details>',
    '<details><summary>{}</summary></details>', '<div>{}</div>'])
def test_native_visible_status_control(wrapper):
    assert classify(TOP + wrapper.format(STATUS) + '</section>')['alive'] is False


@pytest.mark.parametrize('tail', ['<', '<div', '<!-- unfinished'])
def test_unfinished_html_token_unknown_across_python_versions(tail):
    assert classify(CLOSED + tail)['alive'] is None


@pytest.mark.parametrize('identity,expected', [('9999999999', None), ('1234567890', False)])
@pytest.mark.parametrize('shape', ['/jobs/view/{}', '/JOBS/VIEW/role-{}/?tracking=1',
    'https://WWW.LinkedIn.COM/jobs/view/{}/', '/jobs-guest/jobs/api/jobPosting/{}?tracking=1'])
def test_encoded_job_link_identity(identity, expected, shape):
    encoded = ''.join(f'%{ord(c):02x}' for c in identity)
    body = TOP + '<a href="' + shape.format(encoded) + '">' + STATUS + '</a></section>'
    assert classify(body)['alive'] is expected


@pytest.mark.parametrize('href', ['/jobs/view/%2539%2539', '/jobs/view/%zz',
    '/%6Aobs/%76iew/9999999999/', '/jobs/view/9999999999/extra'])
def test_ambiguous_or_encoded_foreign_job_paths_unknown(href):
    assert classify(TOP + f'<a href="{href}">' + STATUS + '</a></section>')['alive'] is None


class WireSocket:
    def __init__(self, wire): self.wire = wire
    def makefile(self, _mode): return BytesIO(self.wire)
    def sendall(self, _data): pass
    def close(self): pass


def wire_response(endpoint, wire, transport):
    if transport == 'pinned-wrapper':
        response = http.client.HTTPResponse(WireSocket(wire))
        response.begin()
        return _Response(response, WireSocket(wire), endpoint)
    class WireConnection(http.client.HTTPConnection):
        def connect(self): self.sock = WireSocket(wire)
    class WireHTTPSHandler(HTTPSHandler):
        def https_open(self, request): return self.do_open(WireConnection, request)
    # Real urllib opener + do_open + HTTPConnection + HTTPResponse; only the
    # socket wire is synthetic, so no public request or redirected identity.
    return build_opener(WireHTTPSHandler()).open(endpoint)


def wire_bytes(headers, body):
    return b'HTTP/1.1 200 OK\r\n' + headers.encode() + b'\r\n\r\n' + body


FRAMING = [
    ('short-length', f'Content-Length: {len(CLOSED.encode()) + 2000}', CLOSED.encode(), None),
    ('complete-length', f'Content-Length: {len(CLOSED.encode())}', CLOSED.encode(), False),
    ('connection-close', 'Connection: close', CLOSED.encode(), False),
    ('complete-chunked', 'Transfer-Encoding: chunked',
     f'{len(CLOSED.encode()):x}\r\n'.encode() + CLOSED.encode() + b'\r\n0\r\n\r\n', False),
    ('missing-final-chunk', 'Transfer-Encoding: chunked',
     f'{len(CLOSED.encode()):x}\r\n'.encode() + CLOSED.encode() + b'\r\n', None),
    ('short-chunk', 'Transfer-Encoding: chunked',
     f'{len(CLOSED.encode()) + 2000:x}\r\n'.encode() + CLOSED.encode(), None),
    ('conflicting-framing', 'Transfer-Encoding: chunked\r\nContent-Length: 1',
     b'1\r\nx\r\n0\r\n\r\n', None),
    ('duplicate-length', f'Content-Length: {len(CLOSED.encode())}\r\nContent-Length: 1', CLOSED.encode(), None),
    ('invalid-length', 'Content-Length: invalid', CLOSED.encode(), None),
    ('over-limit-eof', 'Connection: close', CLOSED.encode() + b' ' * 512000, None),
    ('over-limit-length', 'Content-Length: 600000', CLOSED.encode() + b' ' * 600000, None),
]


@pytest.mark.parametrize('transport', ['pinned-wrapper', 'urllib'])
@pytest.mark.parametrize('_name,headers,body,expected', FRAMING, ids=[row[0] for row in FRAMING])
def test_http_framing_before_closure(transport, _name, headers, body, expected):
    calls = []
    def opener(request, **_):
        calls.append(request.full_url)
        return wire_response(request.full_url, wire_bytes(headers, body), transport)
    assert liveness.check_url(URL, opener=opener)['alive'] is expected
    assert calls == [GUEST]


@pytest.mark.parametrize('attack', ['native-hidden', 'foreign-encoded', 'short-body'])
def test_false_closure_never_persists_or_survives_unknown(connection, monkeypatch, attack):
    pid = database.persist_postings(connection, [{'source': 'linkedin', 'id': '1234567890',
        'title': 'Synthetic Engineer', 'company': 'Synthetic', 'url': URL}], '2026-10-07T13:00:00Z')[0]
    monkeypatch.setattr(recheck.time, 'sleep', lambda _: None)
    def opener(request, **_):
        if attack == 'short-body':
            return wire_response(request.full_url, wire_bytes(FRAMING[0][1], FRAMING[0][2]), 'pinned-wrapper')
        wrapper = HIDDEN[0] if attack == 'native-hidden' else '<a href="/jobs/view/%39%39%39%39%39%39%39%39%39%39">{}</a>'
        return Response(request.full_url, TOP + wrapper.format(STATUS) + '</section>')
    monkeypatch.setattr(recheck, 'pinned_open', opener)
    assert recheck.recheck(connection, scope='linkedin')['unknown'] == 1
    before = connection.execute('select liveness from postings where id=%s', (pid,)).fetchone()[0]
    recheck.recheck(connection, scope='linkedin', checker=lambda _: {'alive': None, 'liveness_reason': 'http-429-uncertain'})
    after = connection.execute('select liveness from postings where id=%s', (pid,)).fetchone()[0]
    assert 'alive' not in before and 'alive' not in after
