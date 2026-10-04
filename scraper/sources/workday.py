"""Anonymous Workday CXS lists; detail pages supply descriptions and dates."""
import html
import json
import re
from datetime import date, datetime, timezone
from urllib.parse import urlparse

USER_AGENT = 'Mozilla/5.0 (compatible; JobRadarCoach/1.0)'
MAX_PAGES = 25
HOST = re.compile(r'([a-z0-9-]+)\.(wd[0-9]+)\.myworkdayjobs\.com')
JOB_PATH = re.compile(r'/job/(?:[A-Za-z0-9._~-]+/)*[A-Za-z0-9.-]+_([A-Za-z0-9-]+)')


def coordinates(url):
    try:
        parsed = urlparse(url)
    except ValueError:
        return None
    host = HOST.fullmatch(parsed.netloc)
    path = re.fullmatch(r'/(?:[a-z]{2}-[A-Z]{2}/)?([A-Za-z0-9._-]+)(/job/[^?#]+)?/?', parsed.path)
    if parsed.scheme != 'https' or not host or not path:
        return None
    job_path = (path.group(2) or '').rstrip('/')
    if job_path and not JOB_PATH.fullmatch(job_path):
        return None
    return {'account': host[1], 'cluster': host[2], 'site': path[1]}, job_path


def base(query):
    for key in ('account', 'cluster', 'site'):
        if not isinstance(query.get(key), str) or not re.fullmatch(r'[A-Za-z0-9._-]+', query[key]):
            raise ValueError('invalid Workday identifier')
    url = f"https://{query['account']}.{query['cluster']}.myworkdayjobs.com/{query['site']}"
    if not coordinates(url):
        raise ValueError('invalid Workday host')
    return url.rsplit('/', 1)[0] + f"/wday/cxs/{query['account']}/{query['site']}"


def _valid_record(job):
    return (isinstance(job, dict) and isinstance(job.get('title'), str) and bool(job['title'].strip())
            and isinstance(job.get('externalPath'), str) and JOB_PATH.fullmatch(job['externalPath'])
            and isinstance(job.get('bulletFields'), list) and bool(job['bulletFields'])
            and isinstance(job['bulletFields'][0], str))


def _page(body, offset=0):
    payload = json.loads(body) if body else None
    if not isinstance(payload, dict) or type(payload.get('total')) is not int or payload['total'] < 0:
        raise ValueError('invalid Workday total')
    jobs = payload.get('jobPostings')
    if not isinstance(jobs, list) or len(jobs) > 20 or (offset == 0 and len(jobs) > payload['total']):
        raise ValueError('invalid Workday page')
    if any(not _valid_record(job) for job in jobs):
        raise ValueError('invalid Workday record')
    return payload


def _israel_facets(facets):
    for facet in facets if isinstance(facets, list) else []:
        if not isinstance(facet, dict):
            continue
        values = facet.get('values', [])
        if facet.get('facetParameter') in {'locationCountry', 'locationHierarchy1'}:
            ids = [item['id'] for item in values if isinstance(item, dict)
                   and item.get('descriptor') == 'Israel' and isinstance(item.get('id'), str)]
            if ids:
                return {facet['facetParameter']: ids}
        nested = _israel_facets(values)
        if nested:
            return nested
    return {}


def active_list(query, *, fetcher, before_request=lambda: None, facets=None, search=''):
    offset, expected, seen = 0, None, set()
    for _ in range(MAX_PAGES):
        before_request()
        data = json.dumps({'appliedFacets': facets or {}, 'limit': 20, 'offset': offset, 'searchText': search}).encode()
        page = _page(fetcher(base(query) + '/jobs', data=data), offset)
        jobs, total = page['jobPostings'], page['total'] or (expected if offset else 0)
        if expected is not None and expected != total:
            raise ValueError('changing Workday list')
        expected = total
        if (not jobs and offset < total) or offset + len(jobs) > total:
            raise ValueError('incomplete Workday list')
        for job in jobs:
            if job['externalPath'] in seen:
                raise ValueError('duplicate Workday record')
            seen.add(job['externalPath'])
            yield job
        offset += len(jobs)
        if offset == total:
            return
    raise ValueError('incomplete Workday pagination')


def is_active(query, path, *, fetcher):
    try:
        search = JOB_PATH.fullmatch(path)[1]
        return any(job['externalPath'].casefold() == path.casefold()
                   for job in active_list(query, fetcher=fetcher, search=search))
    except (OSError, ValueError, TypeError):
        return None


def detail(body, query, path):
    payload = json.loads(body) if body else {}
    info = payload.get('jobPostingInfo') if isinstance(payload, dict) else None
    if not isinstance(info, dict) or coordinates(str(info.get('externalUrl') or '')) != (query, path):
        return {}
    return info


def description(info):
    return ' '.join(html.unescape(re.sub(r'<[^>]+>', ' ', str(info.get('jobDescription') or ''))).split())


def _published(value):
    try:
        return date.fromisoformat(value).isoformat()
    except (TypeError, ValueError):
        return ''


def fetch(query, *, fetcher, before_request, posting_filter=None):
    before_request()
    bootstrap = _page(fetcher(base(query) + '/jobs', data=json.dumps(
        {'appliedFacets': {}, 'limit': 20, 'offset': 0, 'searchText': ''}).encode()))
    facets = _israel_facets(bootstrap.get('facets'))
    if not facets:
        raise ValueError('Workday Israel facet unavailable')
    rows = []
    ids = {key: query[key] for key in ('account', 'cluster', 'site')}
    root = f"https://{query['account']}.{query['cluster']}.myworkdayjobs.com/{query['site']}"
    for job in active_list(query, fetcher=fetcher, before_request=before_request, facets=facets):
        path = job['externalPath']
        row = {'source': 'workday', 'id': f"workday:{query['account']}:{query['site']}:{path.rsplit('/', 1)[-1]}",
            'title': job['title'], 'company': query.get('company', query['account']), 'url': root + path,
            'location': str(job.get('locationsText') or '') + ', Israel', 'raw_text': job['title'],
            'posted_at': '', 'posted_ago': str(job.get('postedOn') or ''), 'alive': True,
            'liveness_reason': 'workday-active-list', 'liveness_checked_at': datetime.now(timezone.utc).isoformat()}
        if posting_filter is not None and not posting_filter(row):
            continue
        before_request()
        try:
            info = detail(fetcher(base(query) + path), ids, path)
        except ValueError:
            info = {}
        locations = [info.get('location'), *(info.get('additionalLocations') or [])]
        if info:
            row['location'] = ', '.join(str(location) for location in locations if location)
        jd = description(info)
        row.update(posted_at=_published(info.get('startDate')), jd_text=jd, jd_fetched=bool(jd), liveness_final_url=row['url'])
        rows.append(row)
    return rows
