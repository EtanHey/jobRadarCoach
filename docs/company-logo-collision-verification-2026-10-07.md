# Logo identity guard verification — 2026-10-07

Status: source verified locally; remote review, merge, deployment and live employer artwork verification belong to the lead.

The old resolver chose a catalog image by canonical company name before inspecting posting URLs. The new resolver binds catalog images to employer domains, requires posting evidence or an explicit unambiguous exception, and rejects competing domains. Unknown names do not invoke Logo.dev name search. Doit is bound to doit.com, so doit.app evidence cannot select the DoiT image. Missing identity falls to initials.

## Verification receipts

- RED before implementation: `node --import tsx --test tests/company-logos.test.ts tests/company-logo-component.test.ts` produced 34 passing / 5 failing tests. The failures covered the Doit app selection, DoiT name-only selection, competing domains, unqualified names, and rendered Doit tile.
- Final `npm test`: 281 server/shared tests plus 20 client tests passed; zero failures or skips. Includes synthetic collision fixtures and complete audit-key inventory checks.
- `npx tsc --noEmit`, `npm run lint`, private-file guard and `git diff --check` passed.
- `company-logos.mjs` against a disposable Next.js app: 7 passed / 0 failed. Desktop and 390 px, light and dark, exercised cards, drawer and globe rail, Doit initials, DoiT catalog selection, loaded conflicting JD, miss-cache reload and transport-error recovery. All Logo.dev requests were intercepted with synthetic responses; no name lookups occurred.
- One suite at a time through `run-suite-capped.sh`, aggregate cap 3072 MB / 600 s: final run exit 0, peak RSS 2184 MB, elapsed 34 s. Actual Next.js GET requests returned HTTP 200; screenshots were inspected for desktop card, mobile Doit drawer and mobile dark rail.
- Audit: SELECT-only snapshot of 1514 hosted postings; all 514 catalog/domain keys inventoried, with 1458 matching postings. Nine candidate mismatches across six names are recorded in the [generated inventory](company-logo-collisions-2026-10-07.generated.md). Candidates may be related domains or redirects; they are not independently proven homonyms.

The first browser attempt had an invalid synthetic score above 100; it was stopped without treating it as feature evidence. The next setup exposed Tailwind scanning the surrounding evidence tree. The final disposable app explicitly restricted CSS sources to its components/lib/app and used a fresh build cache. Only the task fixture process trees were stopped; the production analysis service was untouched.

## Surface coverage

- Entry points — Checked: job-board grid, drawer opening, globe rail; all use the shared resolver and passed browser checks.
- Clients — Checked: desktop and 390 px browser layouts in both themes; shared component rendering tests passed.
- Providers — Checked: local catalog assets, synthetic Logo.dev domain hits/404/network failure and initials; real provider artwork is unverified.
- Contracts — Checked: optional rawJd input from loaded drawer detail; existing summary API remains unchanged, identity metadata and audit inventory tested.
- Reverse states — Checked: no identity, competing URLs/JD, no/invalid publishable key, cached misses and transport recovery; tests passed.
- Connection modes — Checked: credential-free loopback app and simulated request failures; hosted access was audit-only, no production UI/deployment claim.
- Docs — Checked: resolver policy, generated collision inventory, offline reproduction command and this verification receipt reflect the new behavior.

## Limits and next step

Seven of 148 catalog entries have employer-domain bindings; the other 141 cannot select a catalog asset by name. They may resolve through a posting-owned Logo.dev domain when a publishable key is available, otherwise initials. Only Wix and Jeen.ai have explicit unambiguous name-only exceptions. This intentionally trades coverage for employer identity safety.

Cards/rail use summary posting/apply URLs; only the drawer receives JD text. A domain conflict found only in the JD can therefore change the drawer after detail loads. The reported Doit listing has LinkedIn-only URLs and no stored employer domain, so it falls to initials on all surfaces. Preserving DoiT catalog images for ATS-only rows would require trustworthy source-company identity data.

Lead next: review the exact remote head and conservative coverage tradeoff, then own merge/deployment and live-logo QA. No reviewer was started by this worker.
