# LinkedIn guest captures — 2026-10-07

These four minimal fixtures come from unauthenticated HTTP 200 GETs to
`https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/<id>` on 2026-10-07.
`captures.json` records the exact endpoints, original sizes and SHA-256 hashes.
Only the top-card section wrapper, original title and closure figure are retained;
tracking links, images, descriptions, company details and all other markup are removed.
No personal data is included. The closure figure and figcaption are copied verbatim.

- 4469662667 and 4476383841: visible “No longer accepting applications”.
- 4462954347 and 4461128829: no closed status (UNKNOWN, not proof of application availability).

A current guest response with “Not currently accepting applications” was not obtained.
That phrase has explicitly synthetic nested-text controls in `test_linkedin_guest.py`;
it is not presented as a captured provider response. The normal job page is never a
closure source because it can contain other jobs. A guest response that changes
shape, redirects, is incomplete, or supplies ambiguous status remains UNKNOWN.
