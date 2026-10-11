# Company logo domain map

`ui/lib/company-logo-domains.json` contains canonical company names mapped to a confident domain or `null` when identity could not be established. Keys use `canonicalCompanyName` from the shared resolver (NFKC, trimmed, lowercase, collapsed whitespace). A null decision is retained; it is not an unseen company.

Resolution: initials override → conflict-free file/domain override → catalog → posting-owned domain → audited mapped domain → initials. Company-name lookups remain disabled. Ordinary catalog and audited map names retain their existing selection when structured evidence does not conflict. A known collision requires positive identity; the earlier wrong-brand and placeholder overrides still force initials.

`ui/lib/company-logo-identities.json` binds catalog assets to domains, source-company identifiers (LinkedIn employer slug or ATS tenant), and the asset manifest's source posting IDs. `ui/lib/company-logo-source-bindings.json` binds 192 observed posting IDs to the employer heading in their verified source page. DoiT's catalog source links `linkedin:doitintl`; all six DoiT snapshot rows have that employer heading. The incident Doit posting links `linkedin:doit-official` and cannot select DoiT's mark. DoiT's [official ATS board](https://job-boards.greenhouse.io/doitintl) supplies the `greenhouse:doitintl` pin. A bare Doit name stays initials.

Cards, globe rail and drawer pass the same posting ID and posting/apply URLs to the shared resolver. Free-text JD is never identity evidence: partner domains, negated affiliation, email addresses and userinfo URL text can neither grant nor veto a logo after detail loads. Competing non-shared URL domains or conflicting source-company identifiers veto the catalog. No summary API change is required.

The complete inventory is in [the Oct 7 collision audit](company-logo-collisions-2026-10-07.generated.md). To reproduce against a privately stored SELECT-only snapshot (`id, company, url, apply_url, raw_jd`), run from `ui/`:

```sh
node --import tsx ../scripts/build-logo-source-bindings.ts /path/to/private-snapshot.json /path/to/stored-source-pages /path/to/additional-source-pages
node --import tsx ../scripts/audit-logo-collisions.ts /path/to/private-snapshot.json /path/to/report.md
```

Both scripts read no secrets and perform no network calls. The binding builder reads only the employer-heading anchor, checks its label against the posting company, and verifies the manifest source page hash where recorded; related-company links elsewhere in HTML do not establish identity. Snapshot ATS tenants extend bindings for ordinary names. Collision pins require reviewed identity; never add an ATS tenant for a collision solely from its display name. The audit emits posting IDs and structured evidence without raw JD/contact data.

The frozen 1,514-row regression fixture contains public posting IDs, company names and URLs with queries/fragments removed, plus baseline catalog/domain selections. It excludes JD and name-search results. It tests at least 95% retention and agreement across detail loading, and separately checks the known wrong-company row and all six DoiT rows. Source selection counts do not prove live provider responses or artwork correctness.

## Refresh unseen companies

Prepare a JSON array of company names, then from `ui/` run:

```sh
node --import tsx ../scripts/refresh-logo-domains.ts /path/to/company-names.json ../ui/lib/company-logo-domains.json
```

Provide `LOGO_DEV_SECRET_KEY` in the environment through your normal secret manager. Do not paste it into commands, files, logs or PRs. The script uses [Logo.dev Brand Search](https://www.logo.dev/products/brand-search-api) with `strategy=match`, accepts a result only if its canonical brand name or domain label exactly equals the canonical company name, AND its first domain label resembles the company (joined tokens with/without corporate suffixes, a distinctive token of at least four characters, or company initials), and stores only the domain. This additional guard follows the lead’s review ruling; it is a conservative identity heuristic, not proof of domain ownership. It never stores returned logo URLs or tokens. Review the generated map before committing.

Existing entries, including null, are never queried or changed. Duplicate canonical names are queried once. Requests run sequentially, with one second between the previous response and the next request. An HTTP/network/invalid-response failure stops the refresh without replacing the output. A successful refresh replaces the map atomically. No refresh runs in CI, and the browser never receives the search secret.

A confident identity is not proof that its CDN image exists or that its artwork is correct; the miss cache and initials fallback still apply. Release QA must inspect real company marks. Coverage counts should separate identity-qualified catalog/domain selections from initials. A resolved URL does not establish artwork correctness.

## Evidence-backed restorations (Oct 11)

The [generated ownership report](company-logo-restorations-2026-10-11.generated.md) accounts for all 196 previously nulled domains: 166 restored, 30 still initials. The frozen fixture gains 308 source selections with zero previous losses; six company names retain some unverified rows. These are identity-qualified selections, not live artwork counts.

`scripts/company-logo-restorations.json` contains **reviewed** employer-profile Website pins, public source URLs, posting IDs and page hashes. Verify the linked profile’s explicit Website field before adding a pin; the offline builder validates recorded fields and source hashes, and cannot independently authenticate a claimed Website field. A profile Website subdomain establishes its parent registrable domain; a separately verified HTTPS redirect can establish a destination domain. The report records corrections to the old unproven candidates.

Reproduce the additive restoration from the retained SELECT-only snapshot, homepage receipts and exact posting/guest-page bytes (never JD or name guesses):

```sh
node --import tsx ../scripts/build-logo-source-bindings.ts --restore /path/to/snapshot.json ../scripts/company-logo-restorations.json /path/to/homepage-receipts /path/to/posting-pages
```

This mode validates the entire batch before writing. It refuses conflicting existing identities/domains/bindings and preserves prior generated records. The default full binding rebuild also includes these reviewed positive-proof pins; supply all prior source-page directories when replacing the full binding inventory. New pins set `collision: true` to require positive identity even when no homonym has been observed. Unknown rows and conflicting employers keep initials.
