# Repost links

UI grouping uses the loaded, filtered cohort after resolving unique IDs. It
requires the same normalized company and compatible location, plus either the
same normalized title or a shared canonical role-specific URL. Matching titles
link within and across sources, including different external/requisition IDs.
Description similarity, fingerprints and embeddings are not required. Grouping adds no database schema, migration or hosted write.
The repost marker adds an optional summary evidence field from existing liveness JSON.

Identity text uses NFKC, collapsed whitespace and lowercase. A small tested table
recognizes Israeli city aliases and their district/country containment, selected
US cities/states, and country names. Haifa links to Haifa District or Israel;
Tel Aviv links to Tel Aviv-Yafo or Tel Aviv District. Known mutually exclusive
cities, districts/states or countries stay separate. Broad, unknown and remote
locations cannot prove exclusion; ambiguous country/state codes alone are not
US evidence. No external geocoder or API is used. Two distinct cities at one
company stay separate even if both are contained by a third country-only row:
every group member must be compatible with every other member. Membership is
deterministic within a company under input permutations.

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
Posted-date sorting therefore ranks a linked group by its earliest known original
publication. Location exclusion and aliases are limited to the table above and
recognized city/country forms. Grouping prepares listing identities once and
caches location facts only for that call; drawer alternates recompute when the
loaded listings, selected ID or detail changes.

This policy follows the lead's revised 2026-10-04 brief: title/company/location
are sufficient, even for two potentially live requisitions. Two genuinely
independent same-title openings at the same location may therefore collapse;
the alternate selector preserves access to both. Only loaded members contribute
dates/evidence, so filters/pagination can hide earlier listings. Historic dates
lost before L5 cannot be recovered. L5's migration must apply in one transaction
before its merge. Real hosted measurements/example pairs remain private under
`docs.local/l6`; committed tests use synthetic listings only.

## Repost marker evidence

LinkedIn cards and drawer headers show `Reposted <age>` only from a visible
`posted-time-ago__text` label beginning with `Reposted` on a complete same-job
guest fragment. Harvest and recheck store the label, observation time and original
posting URL in `liveness.linkedin_reposted_signal`. The age is LinkedIn's wording
at the observation time; it is not recalculated from JRC discovery. A later
unknown, ordinary age label or failed fetch retains the previously seen evidence.
The marker is hidden if the stored URL differs from the current posting.

Removed: discovery-time earlier-listing counts, their card prop and both
LinkedIn publication-range and alternate-count repost guesses. Grouping,
alternate selection and publication-date icons remain. ATS markers, including
listings with alternates, still require a latest source publication after its
original publication. Grouping retains the representative listing's own dates
separately for marker evidence, and drawer markers use the selected listing before
merging display dates. Aggregate group date ranges do not qualify
as evidence for the marker.
