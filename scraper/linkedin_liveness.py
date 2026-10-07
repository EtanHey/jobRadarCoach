"""Accept closure only from the requested guest fragment's own visible status."""
from html.parser import HTMLParser
import re
from urllib.parse import urlparse

BODY_LIMIT = 512_000
REQUEST_INTERVAL = 2.0
PHRASE = re.compile(r'^(no longer accepting applications|not currently accepting applications)$', re.I)
VOID = frozenset('area base br col embed hr img input link meta param source track wbr'.split())
NONVISIBLE = frozenset('script style template noscript svg canvas'.split())
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


class _Fragment(HTMLParser):
    def __init__(self, identity):
        super().__init__(convert_charrefs=True)
        self.identity, self.stack, self.statuses = identity, [], []
        self.uncertain, self.topcards, self.roots = False, 0, 0

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
        # Unknown inline CSS cannot establish visibility. This includes comments/escapes.
        hidden = (any(key in attrs for key in ('hidden', 'inert', 'style')) or
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
        linked = re.search(r'/jobs/(?:view/(?:[^/?]*-)?|api/jobPosting/)([0-9]+)', href)
        if linked and linked.group(1) != self.identity:
            self.uncertain = True
        own_topcard = topcard or bool(parent and parent['topcard'])
        figure = tag == 'figure' and 'closed-job' in classes and own_topcard
        caption = tag == 'figcaption' and 'closed-job__flavor--closed' in classes
        if caption:
            if not (parent and parent['figure'] and own_topcard):
                self.uncertain = True
            self.statuses.append([])
        status = self.statuses[-1] if caption else (parent['status'] if parent else None)
        frame = dict(tag=tag, excluded=excluded, hidden=hidden, topcard=own_topcard,
                     figure=figure, status=status)
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
        if frame['status'] is not None and not frame['hidden'] and not frame['excluded']:
            frame['status'].append(data)


def closure_phrase(body, identity):
    parser = _Fragment(identity)
    parser.feed(body)
    parser.close()
    if parser.uncertain or parser.stack or parser.topcards != 1 or len(parser.statuses) != 1:
        return None
    text = ' '.join(''.join(parser.statuses[0]).split())
    match = PHRASE.fullmatch(text)
    return match.group(1).lower() if match else None
