# Company logo domain map

`ui/lib/company-logo-domains.json` contains canonical company names mapped to a confident domain or `null` when identity could not be established. Keys use `canonicalCompanyName` from the shared resolver (NFKC, trimmed, lowercase, collapsed whitespace). A null decision is retained; it is not an unseen company.

Resolution: override → curated catalog → trusted company-site posting domain → mapped domain → name lookup for companies absent from the map → initials. Map-null companies show initials when no earlier source resolves them. Both Yael Korentec Technologies and Yael Group, plus the existing wrong-brand pins, always show initials. All CDN requests retain the existing size/format/theme/fallback parameters and confirmed-404 miss cache.

## Refresh unseen companies

Prepare a JSON array of company names, then from `ui/` run:

```sh
node --import tsx ../scripts/refresh-logo-domains.ts /path/to/company-names.json ../ui/lib/company-logo-domains.json
```

Provide `LOGO_DEV_SECRET_KEY` in the environment through your normal secret manager. Do not paste it into commands, files, logs or PRs. The script uses [Logo.dev Brand Search](https://www.logo.dev/products/brand-search-api) with `strategy=match`, accepts a result only if its canonical brand name or domain label exactly equals the canonical company name, and stores only the domain. It never stores returned logo URLs or tokens. Review the generated map before committing.

Existing entries, including null, are never queried or changed. Duplicate canonical names are queried once. Requests run sequentially, with one second between the previous response and the next request. An HTTP/network/invalid-response failure stops the refresh without replacing the output. A successful refresh replaces the map atomically. No refresh runs in CI, and the browser never receives the search secret.

A confident identity is not proof that its CDN image exists or that its artwork is correct; the miss cache and initials fallback still apply. Release QA must inspect real company marks. Before/after resolver coverage counts must separate catalog/domain selections, unverified name lookups and initials; a successful name lookup alone does not establish brand correctness.
