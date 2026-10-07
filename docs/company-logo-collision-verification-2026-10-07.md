# Logo collision guard — fix round 1, 2026-10-07

Status: local source verification; remote publication, replacement-head review, merge, deployment and live provider/artwork QA remain pending.

The rejected head d917b9a treated arbitrary JD mentions as employer identity and removed 580 of 600 previous catalog selections. The replacement removes JD evidence entirely, preserves ordinary catalog/audited map names absent structured conflicts, and requires positive proof for the observed Doit/DoiT collision. Cards, rail and drawer now pass the same posting ID/URLs.

## Identity evidence and acceptance

- Original SELECT-only snapshot: 1,514 postings, taken October 7. A fresh SELECT-only metadata query returned the same 1,514 IDs and no stored LinkedIn employer ID/slug fields: `liveness` contains status/check metadata; `list_metadata` contains stack, experience and description availability. No hosted data was modified.
- 192 posting-to-company bindings come from employer-heading anchors in stored/public source pages. All six DoiT rows link `linkedin:doitintl`. The incident row f0dc6b0d-5897-4e50-9946-5e91aae3e321 links `linkedin:doit-official`. The manifest's DoiT asset source links doitintl and its page hash matches the cached source. Three missing DoiT pages plus the incident page were fetched publicly; related-employer links were excluded. No identity was inferred from JD or capitalization.
- The manifest's existing source posting IDs are included in identity records, including verified official assets. Structured ATS tenants are bound from snapshot URLs for ordinary names; the collision's [DoiT ATS pin](https://job-boards.greenhouse.io/doitintl) is verified separately.
- Prior resolver selected 896 catalog/domain sources: 600 catalog and 296 Logo.dev domain selections. The 33 old name searches are outside that denominator. Replacement retains 895/896 (99.89%) with the same source kind/path; catalog retains 599/600. The sole removed selection is independently verified wrong-company Doit. Excluding it gives 895/895 (100%) retained. These are source selections, not 895 independently inspected provider images.
- Known wrong-company cases selecting the rejected asset: 0. All six verified DoiT rows retain the DoiT catalog. Across all 1,514 rows, summary and loaded drawer have 0 resolver disagreements; rail uses the same summary/card path. Observed multi-employer names among source-heading bindings: Doit only. Existing suspect-brand/placeholder initials pins remain covered.
- The committed frozen fixture strips URL query/fragment values and omits JD/contact text. Its retention test requires ≥95%; independent collision/detail tests protect against simply restoring every name match.

## Local verification receipts

- RED first: replacement expectations against d917b9a produced 31 passing / 5 failing tests. Intended failures: JD veto, ordinary catalog coverage, JD grant, and structured DoiT retention. The partner/negation/email/userinfo probe classes are covered.
- UI suite: 287 server/shared plus 20 client tests passed, 0 failures/skips. Typecheck and lint passed. Audit-only rerun after adding structured evidence fields: 2 passed, 0 failed/skipped.
- Generated audit: all 514 catalog/domain keys inventoried, 1,458 matching postings. One structured conflict: incident Doit employer identifier. Old nine JD-domain candidates disappeared when free text was removed; they were never proven separate employers.
- Final capped running Next.js browser suite: 7 passed / 0 failed, exit 0, peak RSS 1,259 MB, elapsed 72 s. Desktop/390 px light/dark cover card/drawer/rail, ordinary catalog and official source-ID assets, DoiT ATS identity, and homonym JD partner/negation/email/userinfo rejection. Cache/reload and transport recovery passed. Desktop homonym drawer, mobile DoiT drawer and mobile dark rail screenshots were inspected. Local catalog assets are real; Logo.dev responses are synthetic. No production artwork/deployment claim.
- First expanded browser run: desktop/cache/transport checks passed, mobile timed out while checking unvisited lazy images. Failure screenshot confirmed loaded top tiles and offscreen pending images. The harness now scrolls each tile into view before checking it; production lazy loading is unchanged.

## Surface coverage

- Entry points — Checked: job-board grid, drawer opening/detail load, globe rail; shared resolver plus browser fixtures.
- Clients — Checked: desktop and 390 px browser layouts, light/dark; component and snapshot contracts.
- Providers — Checked: local catalog assets, synthetic Logo.dev domain hit/404/transport recovery, initials. Live provider artwork remains lead-owned.
- Contracts — Checked: posting ID prop in card/drawer; summary API unchanged; identity/source-binding JSON, manifest source IDs and frozen coverage fixture validated.
- Reverse states — Checked: no identity, conflicting URLs/company identifiers, partner/negation/email/userinfo JD, absent/invalid publishable key, known misses, transport recovery.
- Connection modes — Checked: credential-free loopback Next.js fixture, simulated failures/reload; hosted access SELECT-only.
- Docs — Checked: domain policy, generated collision inventory and this receipt describe structured identity and preservation policy.

No reviewer was launched. No merge, deployment, running production-service mutation, paid logo lookup, or secret-manager access occurred. The push hold remains governed by the lead's instruction.

## Collision source-page provenance

Only the employer-heading anchor was used; related-job company links were excluded. Cached manifest/source pages and public fetched pages have the following SHA-256 receipts.

| Public posting source | Employer identifier | Source page SHA-256 |
| --- | --- | --- |
| [LinkedIn posting 4464359082](https://il.linkedin.com/jobs/view/backend-engineer-data-attribute%E2%84%A2-at-doit-4464359082) | linkedin:doitintl | 321430df568b5d182c34df2affb97d42f0720b0f3a32e078c1db3dae0f9e2ecf |
| [LinkedIn posting 4463977397](https://il.linkedin.com/jobs/view/senior-full-stack-engineer-ai-cost-visibility-at-doit-4463977397) | linkedin:doitintl | 63ed3a92ae557ab1a1e0c50fc960eb1d255227cfb74a78b3aa3bb7f4b4a638a8 |
| [LinkedIn posting 4449816033](https://il.linkedin.com/jobs/view/software-engineer-golang-attribute%E2%84%A2-at-doit-4449816033) | linkedin:doitintl | 855197676829ee00728b868bfc51dd1e94a80ffda1541d089332741f3b60bae1 |
| [LinkedIn posting 4463965907](https://il.linkedin.com/jobs/view/full-stack-engineer-cloud-saas-integrations-at-doit-4463965907) | linkedin:doitintl | abc2f5542180e446fcb0c6906448b9ab508389582a3b907116eb23098983d991 |
| [LinkedIn posting 4452247569](https://il.linkedin.com/jobs/view/engineering-manager-analytics-house-at-doit-4452247569) | linkedin:doitintl | 6f1ab26500650d3e1a223668f9f763b6f094b15b6b1395068735564cacd12010 |
| [LinkedIn posting 4476528919](https://www.linkedin.com/jobs/view/full-stack-engineer-at-doit-4476528919) | linkedin:doit-official | b94d69380ce396ed50f24651fabcf17bd65d84a954b37b11d15d51b8efec0834 |
| [LinkedIn posting 4462237104](https://il.linkedin.com/jobs/view/backend-engineer-data-attribute%E2%84%A2-at-doit-4462237104) | linkedin:doitintl | 72b0107be91b9c4db450dd84c7d509f937e70386ce0ce98a76f186419f8551ec |
