"""Bounded read-only provider details, authenticated by a live tenant sibling."""

import http.client
import json
from urllib.error import HTTPError
from urllib.request import Request

from scraper.sources import workday

USER_AGENT = "JobRadarCoach/1.0 (+https://jobradarcoach.vercel.app)"
BODY_CAP = 2_000_000
ASHBY_QUERY = ("query ApiJobPosting($organizationHostedJobsPageName: String!, $jobPostingId: String!) { "
               "jobPosting(organizationHostedJobsPageName: $organizationHostedJobsPageName, "
               "jobPostingId: $jobPostingId) { id } }")


def _detail(source, tenant, identifier, paths, *, opener, sleep):
    if source == "ashby":
        endpoint = "https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting"
        data = json.dumps({"operationName": "ApiJobPosting", "query": ASHBY_QUERY,
                           "variables": {"organizationHostedJobsPageName": tenant,
                                         "jobPostingId": identifier}}).encode()
    else:
        query, _ = workday.coordinates("https://" + tenant)
        endpoint, data = workday.base(query) + paths[identifier], None
    sleep(1)
    request = Request(endpoint, data=data, headers={"User-Agent": USER_AGENT,
                      "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with opener(request, timeout=10) as response:
            if response.getcode() != 200 or response.geturl() != endpoint:
                return None, None
            body = bytearray()
            while True:
                chunk = response.read(min(65_536, BODY_CAP + 1 - len(body)))
                if not chunk:
                    break
                body.extend(chunk)
                if len(body) > BODY_CAP:
                    return None, 200
        payload = json.loads(body.decode("utf-8"))
        if source == "ashby":
            if not isinstance(payload, dict) or "errors" in payload or not isinstance(payload.get("data"), dict):
                return None, 200
            data = payload["data"]
            if "jobPosting" in data and data["jobPosting"] is None:
                return False, 200
            posting = data.get("jobPosting")
            return (True if isinstance(posting, dict) and posting.get("id") == identifier else None), 200
        return (True if workday.detail(json.dumps(payload), query, paths[identifier]) else None), 200
    except HTTPError as error:
        return (False if source == "workday" and error.code == 404 and error.geturl() == endpoint else None), error.code
    except (OSError, ValueError, TypeError, KeyError, http.client.HTTPException):
        return None, None


def controlled_detail(posting, key, job, board, *, opener, sleep):
    ids, error, _ = board.cache.get(key, (None, None, None))
    if not ids or error is not None or job in ids:
        return None, None
    source, tenant = key
    paths = dict(board.detail_paths.get(key, {}))
    if source == "workday":
        _, paths[job] = workday.coordinates(posting["url"])
    if key not in board.detail_controls:
        control = _detail(source, tenant, min(ids), paths, opener=opener, sleep=sleep)
        board.detail_controls[key] = control[0] is True
    if not board.detail_controls[key]:
        return None, None
    return _detail(source, tenant, job, paths, opener=opener, sleep=sleep)
