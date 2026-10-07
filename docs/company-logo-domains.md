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
