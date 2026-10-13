# Posting work modes

`postings.work_mode` is nullable `hybrid`, `remote`, or `on-site`.
`work_mode_source` records structured source data, a location label, or extracted evidence.
Precedence is structured ATS mode/boolean > parsed location label > extracted evidence.
Extraction preserves both structured and location-derived modes; re-scrape can
replace an extracted mode with a location label, keeping event order consistent.
Hybrid keeps the compatibility `remote` boolean null. A city alone leaves the mode unknown.

Location inference accepts trailing English labels, balanced parentheses/brackets,
and leading Remote - country / Remote (country) / Remote, country forms,
case variations, and separator forms. Conflicting labels stay unknown.
Legacy word-boundary remote inference is retained for multi-location ATS strings
that do not yield one canonical mode. An existing canonical mode keeps its
compatibility boolean when such a rescrape supplies no new mode.
Lever supplies its structured `workplaceType` and Comeet its `workplace_type`; other adapters reach
the shared location parser through posting persistence. No Hebrew mode labels
were present in the measured data.

## Migration

NEEDS MIGRATION APPLY. `0020_posting_work_mode.sql` is stacked after #377's
`0019_publication_dates.sql`. Its card projection retains `last_published_at`
before `work_mode`; detail is populated by name. The contract snapshot and
database test ceilings cover 0020. Fresh migration and upgrade from 0019 must
both pass before apply. The migration runs in one transaction.

This is a one-shot migration, not idempotent after success: record its successful
application and do not rerun it. A failure rolls back all DDL; retry only after
fixing the cause. For rollback, first revert/stop code that reads or writes these
columns. In one transaction: drop the `work_mode` attributes from `job_detail`
and `job_card`; restore `_job_card` and `get_job` from migration 0019; drop
`postings_work_mode_provenance`, `work_mode_source` and `work_mode` from
`postings`; notify PostgREST to reload its schema, then commit. Rollback discards
stored mode values, while retaining publication-date behavior. These steps are
verified on disposable PostgreSQL, not executed against hosted data.

Apply the reviewed migration before merging/deploying column readers/writers or
replacing the operator-owned analysis wheel. Hosted apply is lead-only. #401
must merge before #404 so the UI renders its mode icons and location cleanup.

## Backfill and filters

Run `python -m scripts.backfill_work_mode` with `DATABASE_URL` supplied privately
by the operator. The default opens a read-only transaction, reports per-source
mode-change counts and up to 20 examples, and applies nothing. It works before
the migration; inferred modes only fill rows whose mode and legacy remote
boolean are both null. `--apply` is lead-only after migration review/apply and
18:00 IDT on 2026-10-05. Each update compares the current location and requires
both mode fields still to be unspecified; races are counted as skipped.

The API carries an optional nullable `work_mode` for older-response compatibility.
The board and Globe accept separate Hybrid, Remote and On-site filters. Saved
legacy boolean filters retain their meaning, and an explicit work-mode filter
takes precedence. P2 supplies the human-visible mode icons.

Comeet supplies `workplace_type` as `On-site`, `Hybrid`, or `Remote` ([provider reference](https://developers.comeet.com/reference/careers-position-model)). The anonymous adapter maps these to the canonical structured mode before persistence; missing or unsupported values add no structured claim. Hybrid leaves the legacy `remote` boolean null. This uses the existing columns and requires no new migration or historical backfill.
