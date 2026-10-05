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
