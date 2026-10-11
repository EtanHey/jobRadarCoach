# C2 cleanup verification

Status: source verification; production deployment and independent review are lead-owned.
Fixture: synthetic employer/role, LinkedIn evidence URL and 2026-10-11T00:30Z check.

Run from `ui`: `GLOBE_QA_OUTPUT=<durable directory>
<repo>/docs.local/tools/run-suite-capped.sh browser-tests/cleanup-badge.mjs 3072 180`.
The component/CSS binary serves loopback only and aborts external requests.

Four Chromium cases: 1280/390px in America/Los_Angeles and Asia/Jerusalem.
Dates are respectively October 10 and 11; the evidence link remains unchanged,
keyboard focus reaches the badge, and the badge stays inside the viewport.
Screenshots: [390px](badge-390.png), [1280px](badge-1280.png).
Native title tooltip presence is checked; browser chrome tooltip pixels are not captured.

Surface sweep:
- Entry points — checked: card fixture and shared badge unit markup; absent signal renders nothing.
- Clients — checked: desktop/mobile Chromium and SSR markup; no production-auth claim.
- Providers — checked: synthetic evidence only; provider scraping unchanged.
- Contracts — checked: list alias map covers every wire key; neutral/window/poll RPC routing tests.
- Reverse states — checked: cache prefix preserves adjacent filter/availability visits; absent badge signal.
- Connection modes — N/A: no connection lifecycle changes; all fixture requests are loopback.
- Docs — checked: identity-pin instructions and this reproduction recipe.
