# ATS availability

Stored active ATS jobs are rechecked against complete tenant boards, not a generic careers-page redirect. Greenhouse uses its [shared public API](https://docs.greenhouse.io/job-board.html); Lever uses [published postings with pagination](https://github.com/lever/postings-api). Comeet/Workable use the same board formats as the harvest adapters.

`python -m scraper.recheck --limit 60` remains the scheduled writer. ATS checks share one cached board per tenant per run. Only confirmed absence adds `alive=false`; errors, incomplete/malformed responses, unsupported adapters and exhausted page budgets stay unknown and preserve prior conclusive evidence. Source/external ID and URL guard every update; application status and scores are untouched. A board 404 is unknown, not evidence that each job is gone.

Public GETs use the honest JobRadarCoach UA, public-IP-pinned HTTPS without redirects, a ten-second timeout, a two-megabyte body cap, and at least one second after each response on the same host. No company-domain guessing or browser is involved. Tests use synthetic companies only.

Current supported sources: Greenhouse, Lever, Comeet, Workable. Ashby/SmartRecruiters/Workday adapters remain separate unmerged lanes; their stored rows are selected but stay unknown until their active-list readers are integrated. The read-only L15 snapshot had zero rows from those three sources. This change does not migrate the database, dispatch a workflow, change drawer design, or apply the collected tags.
