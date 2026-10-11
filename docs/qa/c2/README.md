# C2 cleanup verification

Status: local source proof; production and independent review remain lead-owned.
Run from `ui` with a durable output directory:
```sh
GLOBE_QA_OUTPUT=<directory> <repo>/docs.local/tools/run-suite-capped.sh browser-tests/cleanup-badge.mjs 3072 180
```
Synthetic real card/CSS, long employer name, ATS republication and explicit LinkedIn repost.
Eight Chromium cases: 1280/390px, Los Angeles/Jerusalem, ATS/LinkedIn. RED reproduced
company-name collapse and missing checked-date tooltip; GREEN preserves full labels,
company space, keyboard focus, evidence links and viewport bounds across local midnight.
[Screenshots: 390px ATS](badge-390.png), [1280px LinkedIn](badge-1280.png).
Surface sweep:
- Entry points — checked: card/browser, shared badge unit markup, drawer evidence tooltip.
- Clients — checked: desktop/mobile Chromium and SSR; no production-auth claim.
- Providers — checked: synthetic evidence; scraping unchanged.
- Contracts — checked: exhaustive wire aliases and neutral/window/poll RPC routing.
- Reverse states — checked: adjacent cache visits, absent/mismatched repost evidence and Reset.
- Connection modes — N/A: no lifecycle changes; fixture requests are loopback only.
- Docs — checked: pin instructions and this recipe. Native title-tooltip pixels are not captured.
