"""Extract advisory closure evidence from a guest fragment; never decide liveness."""
from html.parser import HTMLParser
import http.client
import re
from urllib.parse import unquote, urlparse

REPOST = re.compile(r"^Reposted [1-9][0-9]* (?:minute|hour|day|week|month|year)s? ago$", re.I)

BODY_LIMIT = 512_000
REQUEST_INTERVAL = 2.0
PHRASE = re.compile(r'^(no longer accepting applications|not currently accepting applications)$', re.I)
VOID = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
NONVISIBLE = frozenset('script style template noscript svg canvas textarea select iframe object'.split())
EXCLUDED = NONVISIBLE | {'aside', 'nav', 'footer'}


def job_id(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or '').lower()
        if (parsed.scheme != 'https' or not (host == 'linkedin.com' or host.endswith('.linkedin.com'))
                or parsed.port not in (None, 443) or parsed.username or parsed.password):
            return None
        match = re.fullmatch(r'/(?:jobs/view/(?:[^/]*-)?|jobs-guest/jobs/api/jobPosting/)([0-9]+)/?', parsed.path)
        return match.group(1) if match else None
    except ValueError:
        return None


def guest_url(url):
    identity = job_id(url)
    return f'https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{identity}' if identity else None


def linked_job_id(href):
    # Links are veto evidence, including relative/foreign-origin and encoded paths.
    path = unquote(urlparse(href).path, errors='strict').lower().rstrip('/')
    prefix = re.search(r'/(?:jobs/view/|(?:jobs-guest/)?jobs/api/jobposting/)', path)
    if not prefix:
        return None
    match = re.fullmatch(r'(?:[^/]*-)?([0-9]+)', path[prefix.end():])
    if not match or '%' in path:
        raise ValueError('ambiguous job link')
    return match.group(1)


def _read_chunked_body(response):
    # stdlib accepts EOF in trailers and discards unchecked chunk delimiters.
    # Validate the raw framing ourselves, for both pinned and urllib responses.
    raw = getattr(response, '_http_response', response)
    if not isinstance(raw, http.client.HTTPResponse) or not raw.chunked or raw.fp is None:
        raise ValueError('unverifiable chunked transport')
    body = bytearray()
    while True:
        line = raw.fp.readline(65_537)
        if len(line) > 65_536 or not re.fullmatch(rb'[0-9a-fA-F]+(?:;[^\r\n]*)?\r\n', line):
            raise ValueError('incomplete chunk header')
        size = int(line.split(b';', 1)[0].strip(), 16)
        if size == 0:
            trailer_bytes = 0
            while True:
                trailer = raw.fp.readline(65_537)
                trailer_bytes += len(trailer)
                if (not trailer.endswith(b'\r\n') or trailer_bytes > 65_536):
                    raise ValueError('incomplete chunk trailers')
                if trailer == b'\r\n':
                    return bytes(body)
                if b':' not in trailer:
                    raise ValueError('invalid chunk trailer')
        if size > BODY_LIMIT - len(body):
            raise ValueError('over-limit chunked body')
        chunk = raw.fp.read(size)
        if len(chunk) != size or raw.fp.read(2) != b'\r\n':
            raise ValueError('incomplete chunk body')
        body.extend(chunk)


def read_guest_body(response):
    """Read to framed completion (or connection EOF), bounded at cap plus one."""
    headers = getattr(response, 'headers', {})
    lengths = (headers.get_all('Content-Length', []) if hasattr(headers, 'get_all')
               else [headers['Content-Length']] if headers.get('Content-Length') is not None else [])
    transfer = (headers.get('Transfer-Encoding') or '').strip().lower()
    # Unsupported/ambiguous framing cannot authenticate a complete fragment.
    if transfer and (transfer != 'chunked' or lengths):
        raise ValueError('ambiguous HTTP framing')
    if len(lengths) > 1 or (lengths and not re.fullmatch(r'[0-9]+', lengths[0].strip())):
        raise ValueError('invalid Content-Length')
    body = _read_chunked_body(response) if transfer else response.read(BODY_LIMIT + 1)
    if len(body) > BODY_LIMIT or (lengths and len(body) != int(lengths[0])):
        raise ValueError('incomplete or over-limit body')
    # Bounded stdlib reads without Content-Length consume through connection EOF.
    # Never decode before this gate.
    return body


class _Fragment(HTMLParser):
    def __init__(self, identity):
        super().__init__(convert_charrefs=True)
        self.identity, self.stack, self.statuses = identity, [], []
        self.uncertain, self.topcards, self.roots = False, 0, 0
        self.closed_figures, self.open_controls, self.reposts = 0, [], []

    def handle_decl(self, _decl):
        self.uncertain = True  # Full documents are not per-job guest fragments.

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        classes = set((attrs.get('class') or '').split())
        if len(attrs) != len(attributes):
            self.uncertain = True
        parent = self.stack[-1] if self.stack else None
        topcard = tag == 'section' and 'top-card-layout' in classes
        if not parent:
            self.roots += 1
            # Real guest fragments: top card, optional description, hidden code metadata.
            if not ((self.roots == 1 and topcard) or
                    (self.roots > 1 and ((tag == 'div' and 'decorated-job-posting__details' in classes) or tag == 'code'))):
                self.uncertain = True
        if topcard:
            self.topcards += 1
            if parent:
                self.uncertain = True
        excluded = tag in EXCLUDED or bool(parent and parent['excluded'])
        first_summary = bool(parent and parent['closed_details'] and tag == 'summary'
                             and not parent['summary_seen'])
        if parent and parent['closed_details'] and tag == 'summary':
            parent['summary_seen'] = True
        # Unknown inline CSS cannot establish visibility. This includes comments/escapes.
        hidden = (any(key in attrs for key in ('hidden', 'inert', 'style', 'popover')) or
                  (tag == 'dialog' and 'open' not in attrs) or
                  bool(parent and parent['closed_details'] and not first_summary) or
                  (attrs.get('aria-hidden') or '').lower() == 'true' or
                  bool(classes & {'hidden', 'invisible', 'sr-only'}) or
                  bool(parent and parent['hidden']))
        if tag in {'html', 'head', 'body', 'style', 'link'} or (
                tag in {'form', 'title'} and not hidden and not excluded):
            self.uncertain = True
        for value in attrs.values():
            identities = re.findall(r'urn:li:jobPosting:([0-9]+)', value or '')
            if any(identity != self.identity for identity in identities):
                self.uncertain = True
        if attrs.get('data-job-id') not in (None, self.identity):
            self.uncertain = True
        href = attrs.get('href') or ''
        try:
            linked = linked_job_id(href)
            if linked and linked != self.identity:
                self.uncertain = True
        except ValueError:
            self.uncertain = True
        own_topcard = topcard or bool(parent and parent['topcard'])
        figure = tag == 'figure' and 'closed-job' in classes and own_topcard
        if 'closed-job' in classes:
            self.closed_figures += 1
        open_control = (own_topcard and not hidden and not excluded and (
            (tag == 'h2' and 'top-card-layout__title' in classes) or
            (tag in {'a', 'button'} and 'apply-button' in classes)))
        if open_control:
            self.open_controls.append([])
        open_text = self.open_controls[-1] if open_control else (parent['open_text'] if parent else None)
        caption = tag == 'figcaption' and 'closed-job__flavor--closed' in classes
        if caption:
            if not (parent and parent['figure'] and own_topcard):
                self.uncertain = True
            self.statuses.append([])
        status = self.statuses[-1] if caption else (parent['status'] if parent else None)
        repost_age = tag == 'span' and 'posted-time-ago__text' in classes and own_topcard
        if repost_age:
            self.reposts.append([])
        repost = self.reposts[-1] if repost_age else (parent['repost'] if parent else None)
        frame = dict(repost=repost, tag=tag, excluded=excluded, hidden=hidden, topcard=own_topcard,
                     figure=figure, status=status, summary_seen=False,
                     open_text=open_text,
                     closed_details=tag == 'details' and 'open' not in attrs)
        if tag not in VOID:
            self.stack.append(frame)
        elif status is not None and not hidden and not excluded:
            status.append(' ')

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1]['tag'] != tag:
            self.uncertain = True
            return
        self.stack.pop()

    def handle_data(self, data):
        if not self.stack:
            if data.strip():
                self.uncertain = True
            return
        frame = self.stack[-1]
        if frame['repost'] is not None and not frame['hidden'] and not frame['excluded']:
            frame['repost'].append(data)
        if frame['open_text'] is not None and not frame['hidden'] and not frame['excluded']:
            frame['open_text'].append(data)
        if (frame['status'] is not None and not frame['hidden'] and not frame['excluded']
                and not frame['closed_details']):
            frame['status'].append(data)


def _validated_fragment(body, identity):
    parser = _Fragment(identity)
    parser.feed(body)
    if parser.rawdata:
        return None
    parser.close()
    return None if parser.uncertain or parser.stack or parser.topcards != 1 else parser


def repost_label(body, identity):
    """Only the visible top-card age label from a complete same-job fragment."""
    parser = _validated_fragment(body, identity)
    if parser is None or len(parser.reposts) != 1:
        return None
    label = ' '.join(''.join(parser.reposts[0]).split())
    return label if REPOST.fullmatch(label) else None


def guest_observation(body, identity):
    """Return (closure phrase, validated open shape); neither changes alive."""
    parser = _validated_fragment(body, identity)
    if parser is None:
        return None, False
    if not parser.statuses:
        # Adopt the captured title/no-closed-figure shape for advisory clearing.
        opened = not parser.closed_figures and any(''.join(text).strip() for text in parser.open_controls)
        return None, opened
    if len(parser.statuses) != 1:
        return None, False
    text = ' '.join(''.join(parser.statuses[0]).split())
    match = PHRASE.fullmatch(text)
    return (match.group(1).lower() if match else None), False


def closure_phrase(body, identity):
    return guest_observation(body, identity)[0]
