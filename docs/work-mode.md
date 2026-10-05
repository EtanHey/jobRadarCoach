# Posting work modes

`postings.work_mode` is nullable `hybrid`, `remote`, or `on-site`.
`work_mode_source` records structured source data, a location label, or extracted evidence.
Structured ATS values take precedence on ingestion, rescrape, and extraction.
Hybrid keeps the compatibility `remote` boolean null. A city alone leaves the mode unknown.

Location inference accepts trailing English labels, balanced parentheses/brackets,
case variations, and separator forms. Conflicting labels stay unknown.
Lever supplies its structured `workplaceType`; the other current adapters reach
the shared location parser through posting persistence. No Hebrew mode labels
were present in the measured data.

## Migration

NEEDS MIGRATION APPLY. The lead must renumber `0019_posting_work_mode.sql`
when integrating queued #377, which also reserves 0019. Adjust the migration
ceiling in the corresponding database tests after renumbering.
Apply the reviewed migration before deploying code that selects/writes these
columns or replacing the operator-owned analysis wheel. No hosted apply is
part of this source change. P2 owns the displayed icons and location cleanup.

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
