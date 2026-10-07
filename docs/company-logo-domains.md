# Company logo domain map

`ui/lib/company-logo-domains.json` contains canonical company names mapped to a confident domain or `null` when identity could not be established. Keys use `canonicalCompanyName` from the shared resolver (NFKC, trimmed, lowercase, collapsed whitespace). A null decision is retained; it is not an unseen company.

Resolution: initials override → identity-qualified file/domain override → identity-qualified catalog → posting-owned domain → explicitly unambiguous mapped domain → initials. Company-name lookups are disabled. A stored domain is an identity candidate, not posting-level corroboration. Both Yael employers and the existing wrong-brand pins always show initials. CDN parameters and confirmed-404 miss caching are unchanged.

`ui/lib/company-logo-identities.json` binds catalog assets to employer domains. Catalog entries without a binding render initials unless a posting-owned domain can resolve through Logo.dev. Doit is bound to `doit.com`; `doit.app` can never select that asset. Only Wix and Jeen.ai currently carry an explicit `unambiguous: true` exception for name-only selection. Different non-ATS posting domains or competing employer-like JD domains veto the exception. Do not add exceptions merely because a domain label resembles the name.

Cards and globe rail use posting/apply URLs; the drawer also checks the loaded JD, including explicit URLs, bare employer domains and email domains. No JD is added to the summary API. If identity is absent, uncertain or conflicting, the logo tile shows initials. A JD domain can change the drawer's selection after detail loads; list tiles cannot check copy that the summary API omits.

The complete read-only inventory and candidate mismatches are in [the Oct 7 collision audit](company-logo-collisions-2026-10-07.generated.md). To reproduce against a privately stored SELECT-only snapshot (`id, company, url, apply_url, raw_jd`), run from `ui/`:

```sh
node --import tsx ../scripts/audit-logo-collisions.ts /path/to/private-snapshot.json /path/to/report.md
```

The audit reads no secrets and performs no network calls. It emits ids/domain candidates without raw job copy or contact details. Candidate mismatches can be related company domains or shared redirects; the report does not claim every mismatch is a distinct employer.

## Refresh unseen companies

Prepare a JSON array of company names, then from `ui/` run:

```sh
node --import tsx ../scripts/refresh-logo-domains.ts /path/to/company-names.json ../ui/lib/company-logo-domains.json
```

Provide `LOGO_DEV_SECRET_KEY` in the environment through your normal secret manager. Do not paste it into commands, files, logs or PRs. The script uses [Logo.dev Brand Search](https://www.logo.dev/products/brand-search-api) with `strategy=match`, accepts a result only if its canonical brand name or domain label exactly equals the canonical company name, AND its first domain label resembles the company (joined tokens with/without corporate suffixes, a distinctive token of at least four characters, or company initials), and stores only the domain. This additional guard follows the lead’s review ruling; it is a conservative identity heuristic, not proof of domain ownership. It never stores returned logo URLs or tokens. Review the generated map before committing.

Existing entries, including null, are never queried or changed. Duplicate canonical names are queried once. Requests run sequentially, with one second between the previous response and the next request. An HTTP/network/invalid-response failure stops the refresh without replacing the output. A successful refresh replaces the map atomically. No refresh runs in CI, and the browser never receives the search secret.

A confident identity is not proof that its CDN image exists or that its artwork is correct; the miss cache and initials fallback still apply. Release QA must inspect real company marks. Coverage counts should separate identity-qualified catalog/domain selections from initials. A resolved URL does not establish artwork correctness.
