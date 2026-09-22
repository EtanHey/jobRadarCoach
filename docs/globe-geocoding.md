# Globe geocoding operator runbook

Status: source tooling; migration/application/deployment belong to the lead.

## Policy and evidence

Read [Nominatim policy](https://operations.osmfoundation.org/policies/nominatim/) before running.
One operator machine and one process/thread only. Prepare, apply and rollback hold the same
user-global lock; apply/rollback retain it through commit and also take a database transaction lock.
Snapshot is read-only and does not need this mutation lock.
No cron. Default pace is four requests/minute. `--one-time` permits <=1 request/second for a small
one-off batch; runs lasting more than a day use the slower limit. Every result, including empty
results, is cached. HTTP failures stop immediately and preserve the cache. Identify the app,
display © OpenStreetMap contributors linking to https://www.openstreetmap.org/copyright,
and retain ODbL attribution. Provider endpoint is configurable; do not send profile/private data.

A single unambiguous city/region/country result is eligible, with range/finite/type validation.
Multiple candidates remain unresolved. Centroids are approximate; HQ is explicitly separate.
HQ evidence is an operator-reviewed JSON array of `company`, `city`, `country`, `source`
(primary HTTPS URL), `verified_at`, `quote`. The geocoder finds that city; it never infers HQ
from a company-name search. A company with multiple HQs requires the operator to select and
explain one in the evidence; the current schema stores one HQ per company.

## Prepare (no database mutations)

Use a Python environment with psycopg installed. Export DATABASE_URL through the existing secret
loader without printing it. Never put the connection string in command arguments or reports.
Use a durable gitignored artifact directory, e.g. `docs.local/globe-data`; retain one shared cache.

```sh
python -m scripts.globe_geocode snapshot --out docs.local/globe-data/postings.json
python -m scripts.globe_geocode prepare --snapshot docs.local/globe-data/postings.json --cache docs.local/globe-data/nominatim-cache.json --out docs.local/globe-data/plan.json --hq-evidence docs.local/globe-data/hq-evidence.json --one-time
```

Omit `--hq-evidence` for pass 1 only. Use `--exclude-queries reviewed-exclusions.json` for a JSON
array of inspected ambiguous posting queries; exclusions override even unique cached matches and
are recorded in the plan. Rerun the identical prepare command with those exclusions to resume.
If Python's CA store is incomplete, point SSL_CERT_FILE at an installed trusted CA bundle;
never disable TLS verification. Review raw cached display names and unresolved rows before apply.
Local snapshots do not establish hosted coverage; snapshot the target database read-only for its plan.

## Lead-owned apply and rollback

Apply reviewed migrations `0016_posting_geo.sql` and `0017_globe_apply_identity.sql` through the
normal release process first. Migration0017 provisions a random target ID and database-OID guard.
Cloned targets require explicit operator identity reprovisioning before use; never copy an identity
to an unrelated database. Preserve the apply journal across target recovery.
Review counts and source URLs in the prepared plan, then explicitly run:

```sh
python -m scripts.globe_geocode apply --plan docs.local/globe-data/plan.json --receipt docs.local/globe-data/apply-001.json
python -m scripts.globe_geocode rollback --receipt docs.local/globe-data/apply-001.json
```

Apply checks posting identity/location/remote against the snapshot and inserts only missing rows
in one transaction. Existing geocodes/HQs are preserved, including on reruns. Use a NEW receipt
path per apply. The function requires an idle connection and owns its transaction. The receipt path
is exclusively reserved before insertion, fsynced and never overwritten; failures can leave an empty
reservation, which must be preserved (choose another path). Successful publication is read-only.
The versioned receipt records target/apply UUIDs, plan hash, source head, exact tooling hash and rows.
It is fsynced before commit; file presence alone does NOT prove commit. Rollback validates its shape
and requires an identical committed apply-journal entry on the current target. A row must still carry
that apply's ownership marker AND its original values. Updates clear ownership; delete/reinsert
cannot inherit it. Legacy receipts, malformed receipts and other-target receipts fail closed.
Never manually transplant markers or journal/target identities. Old plan/cache formats remain valid;
only NEW applies create owned receipts. Existing coordinates retain null ownership and are preserved.
For schema rollback, first disable the globe endpoint/toggle and roll back data via receipts;
retain the additive tables until the lead confirms all consumers and retained data are handled.
Never drop tables as routine cleanup. No production analysis service action is needed.
