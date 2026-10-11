# ATS availability

Ongoing liveness uses an hourly tenant-wide run (`ats-liveness.yml`, minute 37, plus 0–60s start jitter). The six-hour scrape keeps its bounded LinkedIn URL recheck; it does not duplicate ATS checks. The hourly workflow has its own `ats-liveness` concurrency group, while the scrape uses `cloud-scrape`; optimistic row guards protect overlapping writes. GitHub schedules can be delayed; hourly is the configured cadence, not a delivery SLA.

`python -m scraper.recheck --scope ats --jitter` selects every stored ATS row, including inactive rows, with one cached complete active-list retrieval per tenant per run. Lever uses its unfiltered list endpoint without skip/limit, avoiding offset races and individual API lookups for routine misses. Greenhouse uses its [shared public API](https://docs.greenhouse.io/job-board.html); Lever uses [published postings with pagination](https://github.com/lever/postings-api). Comeet/Workable use the harvest adapters' board formats. `--limit 60` bounds only LinkedIn checks; `--scope linkedin` retains their existing behavior.

An absent ID is membership evidence only. A posting becomes inactive only after two consecutive successful complete-list misses at least 45 minutes apart AND a direct GET of its own stored URL confirms HTTP 404/410 or a redirect to that tenant's generic careers page. An earlier second observation stays pending and preserves the first strike's time. Legacy strikes without a valid timestamp start a fresh spacing window. The first miss never checks the individual URL; confirmed inactive rows need only the tenant list on subsequent runs. After three inconclusive own-URL checks, further direct checks occur at most once per 24 hours until list presence resets the backoff. Ordinary 200s, visible closure text, auth redirects, foreign redirects and errors are unknown; they preserve prior conclusive availability. Matching list presence resets the streak and automatically reactivates a previously closed posting while preserving its own-URL evidence. A list race therefore cannot close a still-live URL.

For Greenhouse only, an inconclusive stored-URL check also checks `https://job-boards[.eu].greenhouse.io/{board}/jobs/{id}`, built from the stored source/board/job identity. A matching stored Greenhouse URL supplies the US/EU region. The shared board API supplies no regional provenance, so employer-only rows stay unknown rather than defaulting to US. Before trusting canonical closure, a sibling ID present in this run's complete board snapshot must return HTTP 200 on the same canonical host. The control success or failure is cached per tenant per run, with at most one control GET; empty/failed/incomplete boards, missing regional evidence, redirects and control errors remain unknown. Ongoing recheck and tag backfill share their run's BoardChecker with the confirmation gate. The canonical request accepts only HTTP 404 or HTTP 302 to the same HTTPS host and exact board path with query `error=true`. HTTP 200, 410, 429, 5xx, other redirects and timeouts remain unknown. A stored URL already equal to the canonical page needs no duplicate target GET, but still requires the positive control. Closure from legacy or other Greenhouse-hosted URLs is confirmed on the canonical page so a control cannot authenticate a different host/path. The fallback uses the same pinned transport, honest UA and timeout, waits one second before its request, and never follows redirects. Other providers and the two-strike, spacing and backoff rules keep their existing behavior.

Persistence uses existing `postings.liveness` JSON: `ats_miss_count` (0–2), `ats_first_miss_at`, `ats_last_list_checked_at`, `ats_last_seen_in_list`, `ats_url_unknown_count` (0–3), `ats_url_last_attempt_at`, `ats_url_next_check_at`, `ats_unknown_reason`, `ats_alert_count`, and `last_attempt_verdict` (alive/gone/pending/unknown/duplicate-snapshot). Missing keys default safely; no schema migration or hosted migration apply is needed. Cached snapshots cannot supply two strikes. A list error resets the streak, records unknown and increments the alert counter. New uncertainty or a reason/status transition also increments it; repeated identical URL uncertainty and skipped checks do not. Receipts report per-run alerts. Both scheduled workflows run `python -m scraper.run_alerts` even after an earlier step fails: the first source failure, new ATS uncertainty, a failed run, or a missing/invalid receipt emits a GitHub warning without replaying receipt contents. Healthy runs remain quiet; source warnings do not turn a partially successful scrape into a failure. Source config/adapter/tenant failures are counted separately in `result.source_warning_count`, with provider details in the preserved scrape log. The persisted per-posting counter is cumulative. Unknown never erases a prior closure. Updates compare UUID/URL/source/external ID and the original liveness JSON to avoid overwriting concurrent reactivation or scrape evidence. Status/scores stay unchanged.

Board GETs use the honest JobRadarCoach UA, public-IP-pinned HTTPS without redirects, a ten-second timeout, a two-megabyte cap (16 MB for US/EU Lever) and one second after each response per host. Reads use bounded 64 KiB chunks and stop at the cap plus one byte. Exceptional own-URL checks use the same honest UA, pinned transport, no redirect following and a one-second delay before each confirmation. Careers redirects must match the stored tenant and origin; employer-hosted postings accept only same-origin `/careers`, `/jobs` or `/careers/jobs` destinations with no query. Unrecognized destinations stay unknown. Tests use synthetic companies and disposable PostgreSQL only.

Board membership is checked for Greenhouse, Lever, Comeet, Workable, Ashby, SmartRecruiters and Workday. Ashby and Workday now use provider detail signals after the same two-strike gate. Ashby requires error-free public `ApiJobPosting` JSON with explicit `data.jobPosting=null`; Workday requires its own CXS detail HTTP 404. Both first require a matching live sibling detail from this run's complete nonempty tenant snapshot, cached once per source/tenant; absent/failed controls preserve unknown. Bound source/tenant/job identity, pinned HTTPS, no redirects, ten-second timeout, one-second pacing and a two-megabyte response cap apply. [Public probe evidence and limits](ats-provider-detail-research.md) explain why HTML shells and invalid tenant/site responses cannot prove closure. Ashby reuses the public nonpaginated job-board membership validator: every ID and `isListed` flag must be valid, IDs must be unique, and explicit pagination or a mismatched advertised total stays unknown. SmartRecruiters exhausts its existing unfiltered list reader (at most five pages), checking stable totals, offsets and unique records. Workday exhausts its existing CXS JSON POST reader (at most 25 pages of 20), checking totals, offsets and unique identities; its cache separates account, cluster and site. An advertised first-page total above the 500-row traversal cap stops after one request and records stable `board-too-large` uncertainty: the first observation alerts, while repeat runs with the same reason stay quiet. Offset pagination can skip a live posting if a removal and an addition leave the total unchanged during traversal; the own-URL gate prevents closure of a live SmartRecruiters URL, and a live Workday detail remains unknown rather than closing. Workday membership uses the requisition ID, so a changed title slug cannot masquerade as removal. An empty complete board is a valid snapshot, with the same miss and own-URL gates as existing providers. A failed later page invalidates the entire snapshot even if an earlier page contained the job. Workday membership uses empty search and empty facets: the Israel facet remains a discovery filter, since moving outside it cannot prove a posting was removed. A page/body cap, malformed response or incomplete traversal produces unknown, never a miss. Individual Ashby/Workday detail lookups occur only at the exceptional own-URL confirmation gate. No drawer design, collected-tag application, production-service change or workflow dispatch is included here. Lead owns merge and runtime activation.

## Tag backfill

`python -m scripts.backfill_ats_liveness docs.local/reports/2026-10-05-inactive-ats.json` validates the whole tag batch and prints a dry-run receipt with zero network/database actions. Explicit `--apply` uses `DATABASE_URL` and remains frozen before 2026-10-05 18:00 IDT; lead authorization is required. Apply rereads each current identity and liveness state, observes the complete tenant list once, and uses the exact ongoing reliability gate. Old tags do not count as a strike. First misses only record pending state; two consecutive successful misses at least 45 minutes apart plus own-URL closure proof are required. Applying immediately after the hourly first miss stays pending. Reappearance reactivates, new uncertainty increments alerts, repeated URL uncertainty backs off after three checks, and list errors reset strikes. `observed` counts successful guarded state writes; `applied` counts confirmed inactive writes, so recording a first miss is not reported as closure. Concurrent identity/state changes skip writes; the transaction rolls back on failure. No real tags/credentials belong in Git.

## LinkedIn guest advisory badge

LinkedIn closure evidence never sets `alive=false` or hides a job. Harvest and
recheck store `linkedin_closed_signal: {phrase, checked_at, url}` in liveness JSON
(and harvest JSONL). Card and drawer show a linked “LinkedIn: no longer accepting
applications · checked <date>” badge; the alternate supported phrase is displayed
verbatim. Active, New for me and Seen retain their existing status rules. ATS
liveness transitions remain owned by the ATS reliability gate.

The six-hourly rotating recheck selects 60 LinkedIn rows by default (maximum 120),
waits two seconds before each GET, and requests only
`https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/<id>`. Harvest retains its
four-request cloud budget. There are no normal-page fallbacks or retries.

The parser from #443 accepts an HTTP 200 at the exact guest endpoint, a bounded
complete response and a top-card closed-job figure with either supported English
phrase. Other statuses, redirects, unsupported layouts/languages and framing
failures supply no new signal. UNKNOWN updates attempt metadata only; it retains
prior advisory evidence. Newer harvest evidence replaces older evidence; stale
observations do not overwrite it. Scores and application state remain unchanged.

A complete HTTP 200 at the exact guest endpoint clears the advisory signal when
the validated top card has a visible, nonempty title or apply control and no
closed-job figure or status caption. This adopts the captured-open shape from
4462954347 and 4461128829 as advisory reverse evidence; it is not a guarantee that
an application can be submitted. The clear writes `linkedin_closed_signal: null`,
`linkedin_closed_signal_cleared_at` and `liveness_checked_at`, leaving `alive`
untouched. Empty, hidden, malformed, foreign-job, redirected or failed responses
remain UNKNOWN. Harvest without validated evidence preserves the signal; older
closure evidence cannot overwrite a newer clear. A later closure sets a fresh
signal with its own `checked_at`.

Known false positives are deliberately advisory: non-void self-closing hidden
HTML elements and foreign job links containing dot segments/backslashes can
produce a badge. All thirteen r2 examples are retained as real SQL regressions
in `scraper/test_linkedin_badge.py`: a signal is stored but no `alive` field is
written. External CSS is not rendered. The badge is evidence from a checked page,
not a guarantee of current application availability. Previously stored inactive
state is not migrated or reopened by this source change.

Dated minimal provider fixtures and provenance are in
`scraper/fixtures/linkedin-guest`; inherited parsing/framing tests remain. The
alternate English phrase has synthetic controls only; no provider capture is claimed.
