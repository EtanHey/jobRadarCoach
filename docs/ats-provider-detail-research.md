# Ashby and Workday closure evidence (2026-10-11)

Public, read-only probes used the honest JobRadarCoach UA, pinned public HTTPS,
no credentials, no redirects, and no application submissions.

Ashby's [public board API](https://developers.ashbyhq.com/docs/public-job-posting-api)
distinguishes listed from unlisted jobs. Its [posting documentation](https://docs.ashbyhq.com/job-postings)
confirms that unlisted jobs remain applyable by direct link. Therefore list absence
is insufficient. Ashby-hosted live and nonexistent job pages both returned HTTP 200.
Their public detail operation at
`POST https://jobs.ashbyhq.com/api/non-user-graphql?op=ApiJobPosting` returned
`data.jobPosting = {id: ...}` for a listed live job and explicit `null` for a
nonexistent job. A nonexistent tenant also returned `null`. Only error-free JSON
with an explicit null, preceded by a matching live sibling detail from this run's
complete tenant snapshot, confirms closure. A live object, including an unlisted
one, never confirms closure. This undocumented public operation may change;
shape/transport changes fail closed to unknown.

Workday's public CXS detail at
`GET https://nvidia.wd5.myworkdayjobs.com/wday/cxs/nvidia/NVIDIAExternalCareerSite/job/...`
returned HTTP 200 with `jobPostingInfo.externalUrl` for a listed live job and HTTP
404 with an empty body for a nonexistent requisition. A nonexistent site also
returned 404. A live sibling detail must bind the same account/cluster/site and
full job path before a target's own CXS 404 can confirm closure. Other statuses,
redirects, malformed JSON and identity mismatches remain unknown.

The implemented Ashby gate was also exercised against a public Loora board and
a synthetic nonexistent ID: complete membership miss + live sibling control +
null detail produced `ashby-detail-missing`. The implemented Workday detail reader
returned live/200 and gone/404 against NVIDIA. NVIDIA's entire board exceeds the
500-row membership cap, so these detail probes do not claim whole-board acceptance.
Both providers still require two spaced complete-list misses before persistence
can close a posting. An empty board has no live control and cannot prove closure.
