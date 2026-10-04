# Repost links

Grouping happens in the UI over the loaded, filtered cohort, after unique IDs are
resolved. HTTP and globe summaries carry the source external ID and a SHA-256
fingerprint of the normalized JD; full descriptions stay out of summaries. No
new database column, migration, embedding model, or hosted write is needed.

A link requires the same NFKC/whitespace/case-normalized company **and title**,
plus one of:

- A shared role-specific URL on Greenhouse (US/EU boards), Workable (`j` and
  `jobs/view` routes), Lever, Comeet, or LinkedIn. Tracking queries and trailing
  slashes do not change the role identity; tenant and requisition paths do.
- An exact normalized JD fingerprint and two known, equal normalized locations.
  Descriptions shorter than 200 characters or 40 words provide no fingerprint.

Different known locations or contradictory known remote flags always stay
separate. Different ATS requisition URL identities stay separate, even when
one is closed. Different external IDs on the same ATS source stay separate
unless at least one listing is explicitly closed; unknown liveness counts as
potentially live. For JD evidence, that external-ID guard also applies to
LinkedIn. A shared ATS apply URL can link two LinkedIn listing IDs: those IDs
identify advertisements, while the ATS URL identifies the requisition.

Generic careers pages, title alone, discovery time, and refresh time provide
no link evidence. Names/location aliases and semantic similarity are not
inferred; this intentionally leaves uncertain reposts separate. Distinct
cross-source roles with identical descriptions and locations and no known ATS
identity may still look identical; stronger source metadata would resolve that.
All members must pairwise agree, preventing transitive URL/JD bridges. IDs
establish deterministic membership within each company, independent of input
permutations.

The representative is the listing with the newest own original `posted_at`,
falling back to `first_seen_at` only when publication is unknown, then ID.
Its score, title, source and status remain its own. The displayed group's
original publication is the earliest known member `posted_at`; latest
publication is the maximum of member original/latest dates. Best Fit ties
therefore use the group's original date. Cards and drawer headers show these
group dates; alternates retain their own dates. Inputs are never mutated.

Only loaded members contribute evidence and dates. An availability/source/status
filter, pagination, or missing historic source publication may hide earlier
members; this cannot recover the true original date. L5's publication-date
migration remains a separate release prerequisite. The hosted measurement and
real example pairs are private artifacts under `docs.local/l6`, with synthetic
fixtures only in committed tests.
