"""Anonymous SmartRecruiters public lists; details supply text, not liveness."""
from __future__ import annotations

import html
import json
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

MAX_PAGES = 5
USER_AGENT = 'Mozilla/5.0 (compatible; JobRadarCoach/1.0)'


def endpoint(account, job_id=None):
    return f'https://api.smartrecruiters.com/v1/companies/{account}/postings' + (f'/{job_id}' if job_id else '')


def coordinates(url):
    parsed = urlparse(url)
    match = re.fullmatch(r'/([A-Za-z0-9._-]+)/([0-9]+)(?:-[^/]*)?/?', parsed.path)
    if parsed.scheme == 'https' and parsed.netloc in {'jobs.smartrecruiters.com', 'www.smartrecruiters.com'} and match:
        return match.group(1), match.group(2)
    return None


def _valid_page(payload, offset, count):
    total, limit = payload.get('totalFound'), payload.get('limit')
    return (type(total) is int and total >= offset + count and type(payload.get('offset')) is int
            and payload['offset'] == offset and type(limit) is int and 1 <= limit <= 100 and count <= limit)


def _valid_record(job, account):
    if not isinstance(job, dict):
        return False
    company = job.get('company')
    return (isinstance(job.get('id'), str) and re.fullmatch(r'[0-9]+', job['id'])
            and isinstance(job.get('name'), str) and bool(job['name'].strip()) and isinstance(company, dict)
            and isinstance(company.get('identifier'), str) and company['identifier'].casefold() == account.casefold())


def _page(body, account, offset):
    payload = json.loads(body) if body is not None else None
    if not isinstance(payload, dict) or not isinstance(payload.get('content'), list):
        raise ValueError('invalid SmartRecruiters list')
    total = payload.get('totalFound')
    records = payload['content']
    if not _valid_page(payload, offset, len(records)):
        raise ValueError('invalid SmartRecruiters pagination')
    if not records and offset < total:
        raise ValueError('incomplete SmartRecruiters list')
    if any(not _valid_record(job, account) for job in records):
        raise ValueError('invalid SmartRecruiters record')
    return records, total


def active_list(account, *, fetcher, before_request=lambda: None, country=None):
    if not re.fullmatch(r'[A-Za-z0-9._-]+', account):
        raise ValueError('invalid SmartRecruiters account')
    offset, expected_total, seen = 0, None, set()
    for _ in range(MAX_PAGES):
        before_request()
        url = endpoint(account) + f'?limit=100&offset={offset}' + (f'&country={country}' if country else '')
        records, total = _page(fetcher(url), account, offset)
        if expected_total is not None and total != expected_total:
            raise ValueError('changing SmartRecruiters list')
        expected_total = total
        for record in records:
            if record['id'] in seen:
                raise ValueError('duplicate SmartRecruiters record')
            seen.add(record['id'])
            yield record
        offset += len(records)
        if offset == total:
            return
    raise ValueError('incomplete SmartRecruiters pagination')


def is_active(account, job_id, *, fetcher):
    try:
        return any(job['id'] == job_id for job in active_list(account, fetcher=fetcher))
    except (OSError, ValueError):
        return None


def description(body, job_id):
    detail = json.loads(body) if body else {}
    if not isinstance(detail, dict) or detail.get('id') != job_id:
        return ''
    ad = detail.get('jobAd')
    sections = ad.get('sections') if isinstance(ad, dict) else None
    if not isinstance(sections, dict):
        return ''
    text = ' '.join(str(section.get('text') or '') for section in sections.values() if isinstance(section, dict))
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', text)).split())


def _published(value):
    if not isinstance(value, str):
        return ''
    try:
        parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return ''
    return value if parsed.tzinfo is not None else ''


def _summary(job, query):
    location = job.get('location') if isinstance(job.get('location'), dict) else {}
    country = str(location.get('country') or '')
    country = 'Israel' if country.casefold() == 'il' else country
    return {'id': f"smartrecruiters:{query['account']}:{job['id']}", 'source': 'smartrecruiters',
            'title': str(job.get('name') or ''), 'company': query.get('company', query['account']),
            'location': ', '.join(str(value) for value in [location.get('city'), country] if value),
            'remote': location.get('remote') if type(location.get('remote')) is bool else None,
            'url': f"https://jobs.smartrecruiters.com/{query['account']}/{job['id']}",
            'posted_at': _published(job.get('releasedDate')), 'posted_ago': '', 'raw_text': str(job.get('name') or ''),
            'alive': True, 'liveness_reason': 'smartrecruiters-active-list',
            'liveness_checked_at': datetime.now(timezone.utc).isoformat()}


def fetch(query, *, fetcher, before_request, posting_filter=None):
    postings = []
    for job in active_list(query['account'], fetcher=fetcher, before_request=before_request, country='il'):
        posting = _summary(job, query)
        if posting_filter is not None and not posting_filter(posting):
            continue
        before_request()
        body = fetcher(endpoint(query['account'], job['id']))
        try:
            jd = description(body, job['id'])
            detail = json.loads(body) if body else {}
        except ValueError:
            jd, detail = '', {}
        url = detail.get('postingUrl') if isinstance(detail, dict) else None
        if isinstance(url, str) and coordinates(url) == (query['account'], job['id']):
            posting['url'] = url
        posting.update(jd_text=jd, jd_fetched=bool(jd), liveness_final_url=posting['url'])
        postings.append(posting)
    return postings
