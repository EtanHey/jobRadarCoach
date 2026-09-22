"""Conservative, cached Nominatim geocoding for a single operator-controlled batch.

Policy: https://operations.osmfoundation.org/policies/nominatim/
Only public posting locations; no profiles. One process on one machine, no cron.
"""
from __future__ import annotations

import fcntl
import hashlib
import json
import math
import re
import time
from datetime import datetime
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ENDPOINT = 'https://nominatim.openstreetmap.org/search'
USER_AGENT = 'JobRadarCoach/1.0 (https://etanheyman.com; one-time posting locations)'
LOCK = Path.home() / '.local/state/jobradarcoach/geocoding.lock'


def atomic_json(path: Path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.new')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    temporary.replace(path)


@contextmanager
def single_process():
    LOCK.parent.mkdir(parents=True, exist_ok=True)
    with LOCK.open('a+') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise RuntimeError('Another geocoding process holds the operator lock') from None
        yield


def location_query(value):
    if not isinstance(value, str):
        return None
    value = re.sub(r'\s+', ' ', value).strip()
    value = re.sub(r'\s*\((?:hybrid|remote|on[- ]?site)\)\s*', '', value, flags=re.I)
    value = re.sub(r'^(?:remote|hybrid)\s*[-:,]\s*', '', value, flags=re.I)
    if not value or re.fullmatch(r'remote|hybrid|on[- ]?site|worldwide|anywhere|EMEA|EU|TLV', value, re.I):
        return None
    countries = re.findall(r'\b(?:united states|usa?|united kingdom|uk|canada|israel|ireland|estonia|netherlands|sweden)\b', value, re.I)
    aliases = {'us': 'united states', 'usa': 'united states', 'uk': 'united kingdom'}
    if len({aliases.get(country.lower(), country.lower()) for country in countries}) > 1:
        return None
    # Eligibility/territory prose and ambiguous abbreviations are not a single named place.
    if re.search(r'\b(global|customer|client|locations|timezone|candidates|based|within|continental|midtown)\b|location\s*(country|state|city)', value, re.I):
        return None
    if (re.search(r'\barea\b', value, re.I) and value.casefold() not in {'san francisco bay area', 'sf bay area'}) or re.search(r',\s*IL$', value):
        return None
    if value.casefold() == 'airportcity' or re.match(r'^\d+\s', value):
        return None
    # Multiple locations/office labels need explicit human normalization, not a guessed dot.
    if re.search(r'[;&|/]|\boffice\b|\b(?:or|and)\b|https?:', value, re.I):
        return None
    return {'us': 'United States', 'usa': 'United States'}.get(value.casefold(), value)


def resolved_place(results):
    if not isinstance(results, list) or len(results) != 1:
        return None  # A ranked first result is not evidence that a place is unambiguous.
    row = results[0]
    if not isinstance(row, dict):
        return None
    kind = row.get('addresstype')
    precision = ('city' if kind in {'city', 'town', 'village', 'municipality'} else
                 'region' if kind in {'state', 'province', 'region', 'county', 'state_district'} else
                 'country' if kind == 'country' else None)
    if row.get('category') == 'boundary' and row.get('type') == 'administrative' and re.search(r'\bregional council\b', row.get('name', ''), re.I):
        precision = 'region'
    try:
        lat, lng = float(row['lat']), float(row['lon'])
    except (KeyError, TypeError, ValueError):
        return None
    if row.get('osm_type') not in {'node', 'way', 'relation'} or not isinstance(row.get('osm_id'), int):
        return None
    if not precision or not math.isfinite(lat) or not math.isfinite(lng) or not (-90 <= lat <= 90 and -180 <= lng <= 180):
        return None
    return {'lat': lat, 'lng': lng, 'precision': precision,
            'source': f"nominatim:osm:{row.get('osm_type')}:{row.get('osm_id')}",
            'display_name': row.get('display_name', '')}


class Geocoder:
    def __init__(self, cache: Path, *, endpoint=ENDPOINT, one_time=False, fetch=None, clock=time.monotonic, sleep=time.sleep):
        self.cache_path, self.endpoint = cache, endpoint
        self.cache = json.loads(cache.read_text()) if cache.exists() else {}
        self.interval = 1.1 if one_time else 15.1
        self.fetch, self.clock, self.sleep = fetch or self._fetch, clock, sleep
        self.started, self.last = clock(), clock()
        # A restart waits a full interval; a batch resumed after a day uses the slower policy.
        self.old_cache = any(time.time() - datetime.fromisoformat(e['resolved_at']).timestamp() >= 86400 for e in self.cache.values())
        self.requests = 0

    def _fetch(self, url):
        with urlopen(Request(url, headers={'User-Agent': USER_AGENT}), timeout=30) as response:
            return json.load(response)

    def resolve(self, query):
        url = self.endpoint + '?' + urlencode({'q': query, 'format': 'jsonv2', 'limit': 2, 'addressdetails': 1, 'accept-language': 'en'})
        key = hashlib.sha256(url.encode()).hexdigest()
        if key not in self.cache:
            interval = 15.1 if self.old_cache or self.clock() - self.started >= 86400 else self.interval
            if self.last is not None:
                self.sleep(max(0, interval - (self.clock() - self.last)))
            self.last = self.clock()
            results = self.fetch(url)  # HTTP errors stop the run; never cached as unresolved.
            self.requests += 1
            if not isinstance(results, list):
                raise ValueError('Geocoder returned a non-array response')
            self.cache[key] = {'query': query, 'results': results, 'resolved_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())}
            atomic_json(self.cache_path, self.cache)
        entry = self.cache[key]
        place = resolved_place(entry['results'])
        return {**place, 'resolved_at': entry['resolved_at']} if place else None


def hq_eligible(posting):
    # Keep in parity with public.posting_hq_eligible; SQL remains the serving boundary.
    return posting.get('remote') is True or (posting.get('location') or '').strip().lower() in {
        '', 'remote', 'hybrid', 'on-site', 'onsite', 'worldwide', 'anywhere'}


def prepare(postings, geocoder, hq_evidence=(), excluded_queries=()):
    if not isinstance(excluded_queries, (list, tuple)) or not all(isinstance(q, str) for q in excluded_queries):
        raise ValueError('Reviewed query exclusions must be an array of strings')
    excluded_queries = set(excluded_queries)
    geo, unresolved, hq = [], [], []
    companies = {p['company'] for p in postings}
    for evidence in hq_evidence:
        if evidence['company'] not in companies:
            continue
        # An operator-reviewed primary company URL proves identity/HQ; geocoder only locates the city.
        if not evidence.get('source', '').startswith('https://') or not evidence.get('verified_at') or not evidence.get('quote'):
            raise ValueError('HQ evidence needs an HTTPS primary source, quote and verification date')
        place = geocoder.resolve(f"{evidence['city']}, {evidence['country']}")
        if place and place['precision'] == 'city':
            hq.append({k: place[k] for k in ('lat', 'lng', 'resolved_at')} | {
                'company': evidence['company'], 'city': evidence['city'], 'country': evidence['country'],
                'source': evidence['source'] + ' | ' + place['source']})
    for posting in postings:
        query = location_query(posting['location'])
        place = geocoder.resolve(query) if query and query not in excluded_queries else None
        if place:
            geo.append({'posting_id': posting['id'], **{k: v for k, v in place.items() if k != 'display_name'}})
        else:
            unresolved.append({'posting_id': posting['id'], 'location': posting['location'], 'query': query,
                               'reason': 'reviewed_ambiguous' if query in excluded_queries else 'ambiguous_or_missing_place' if query else 'unusable_location'})
    resolved = {r['posting_id'] for r in geo}
    hq_companies = {r['company'] for r in hq}
    mapped = sum(p['id'] in resolved or (p['company'] in hq_companies and hq_eligible(p)) for p in postings)
    return {'posting_geo': geo, 'company_hq': hq, 'unresolved': unresolved,
            'counts': {'total': len(postings), 'mapped': mapped, 'unresolved': len(postings) - mapped}}
