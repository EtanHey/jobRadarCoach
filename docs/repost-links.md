# Repost links

UI grouping uses the loaded, filtered cohort after resolving unique IDs. It
requires the same normalized company and compatible location, plus either the
same normalized title or a shared canonical role-specific URL. Matching titles
link within and across sources, including different external/requisition IDs.
Description similarity, fingerprints and embeddings are not required. There is
no new database schema, summary field, migration or hosted write.

Identity text uses NFKC, collapsed whitespace and lowercase. Location separators
are normalized; two known locations must match. Null/blank and generic Remote,
Anywhere, Worldwide, Remote Anywhere/Worldwide, Fully Remote, or Anywhere in the world locations are
compatible with a known location. Country/city aliases are not inferred. Known
Tel Aviv versus Haifa, or different countries, stay separate. Remote flags alone
do not split equal locations. Every member must agree with every other member,
so an unknown-location bridge cannot collapse two different known locations.
Membership within a company is deterministic under input permutations.

Shared role URLs link title drift. Recognized routes are Greenhouse US/EU boards,
Workable `j`/`jobs/view`, Lever, Comeet, and LinkedIn job detail pages. Tracking
queries and trailing slashes do not change those identities; tenants and job IDs
do. Generic careers pages do not provide strong identity. A strong URL still
requires the same company and cannot override contradictory known locations.

The representative is the listing with the newest own original `posted_at`,
falling back to discovery only when publication is unknown, then ID ascending.
Its score/status/source remain its own. Cards and drawer headers display the
minimum known member original publication and maximum member original/latest
publication; Best Fit ties use the group original. Alternates retain their own
dates, and inputs are not mutated.

This policy follows the lead's revised 2026-10-04 brief: title/company/location
are sufficient, even for two potentially live requisitions. Two genuinely
independent same-title openings at the same location may therefore collapse;
the alternate selector preserves access to both. Only loaded members contribute
dates/evidence, so filters/pagination can hide earlier listings. Historic dates
lost before L5 cannot be recovered. L5's migration must apply in one transaction
before its merge. Real hosted measurements/example pairs remain private under
`docs.local/l6`; committed tests use synthetic listings only.
