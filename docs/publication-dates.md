# Posting publication dates

`posted_at` is the earliest known source publication for a `(source, external_id)`;
`last_published_at` is the latest observed source publication; `first_seen_at` is
when JRC first discovered that identity. The scraper and database trigger preserve
the minimum publication and maximum last-publication values on repeat observations.
Missing or malformed source dates never erase a known date. An edit timestamp is
not evidence of publication or republication.

| Source | Adapter publication field | Limits |
| --- | --- | --- |
| Greenhouse | `first_published` | `updated_at` is separate edit metadata, never a repost date. |
| Lever | `createdAt` (epoch milliseconds) | Creation time; no independent repost date supplied. |
| Workable | Markdown board `Posted` column (UTC date precision) | Board does not distinguish original publication from repost; preserve the earliest observed value. |
| Comeet | None | Only `time_updated` is available; do not label it as publication. |
| LinkedIn | Guest card `<time datetime>` (UTC date precision) | May describe a repost; relative `posted_ago` text alone is never converted into an invented date. |

Best Fit orders by score descending, then earliest-known publication descending
(or first-seen when publication is unknown), then ID ascending. Duplicate groups
still sort by the displayed representative's score. Posted sort and duplicate
selection continue to use `posted_at`, now preserved as the earliest known value.
Cards and drawers show Posted and Found, with Republished only when a later
publication is known; equivalent timestamps in different timezones are not reposts.

Apply `supabase/migrations/0019_publication_dates.sql` before deploying the new
scraper/UI. It backfills latest publication from the existing publication value,
protects old scraper writers during rollout, and appends the new field to the SQL
card/detail contracts. HTTP lists, details and globe snapshots carry it too.
The public UI field is optional for older cached responses and synthetic fixtures.

Historical originals already overwritten cannot be reconstructed by this migration.
An original never observed by JRC may also be unknown behind the first observed
repost. Dates are preserved per source identity; separate IDs are not evidence of
a shared original publication. No hosted migration is applied by source workers.
