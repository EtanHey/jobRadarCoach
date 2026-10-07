# Logged-in tests against local Postgres

Prerequisites: Node >=22.12, Docker running, Supabase CLI **2.116.0**, OpenSSL.
From `ui/`, run `npm ci` and `npx playwright install chromium --only-shell`.
Run one suite at a time:

```sh
/Users/etanheyman/Gits/jobRadarCoach/docs.local/tools/run-suite-capped.sh e2e/db/run-capped.mjs 3072 600
```

Portable/CI equivalent: `npm run test:db`. Both reset the dedicated database
before every run and report elapsed time and peak process-tree RSS. Docker
containers are outside that tree; measure them separately with `docker stats`.
First image pulls count toward the 600-second deadline. No paid model is used.

Individual commands: `npm run test:db:up` starts Supabase and applies all
repository migrations; `npm run test:db:seed` resets **only** this local stack,
reapplies migrations and seeds it; `npm run test:db:down` stops and deletes
**only** this stack's containers/data. The capped runner leaves it available
for inspection. Run down after testing; cap failure may also leave containers.

Project `jrc-p12-test-db` uses API 55431 (HTTPS), Postgres 55432, shadow 55430,
and Mailpit 55434. Never link it to hosted Supabase. Config, generated TLS
certificate/key, owner UUID, copied app, storage state and screenshots live
under ignored `.e2e/`. No production env files or credentials are loaded.
The seed guard refuses any endpoint other than these exact local addresses.

Data: three fictional postings at Synthetic P12 Studio 1–3, three coherent
scores (90/apply), statuses new/seen/applied, and three synthetic city centroids.
One confirmed local-only Auth user: `p12-owner@example.test`, password
`Local-only-P12-password-123!`. No production profile bootstrap is run.

The current app has no password login form. Setup clicks the real **Send setup
or recovery link** button, reads only the local Mailpit inbox and follows the
real Auth verification/callback. It saves storage state once for the smoke
project. HTTPS preserves the existing production auth contract; Node explicitly
trusts the generated certificate, and Playwright accepts it locally.
Next dev overwrites `NODE_EXTRA_CA_CERTS` with custom HTTPS certs, so its child
uses `--use-openssl-ca` / `SSL_CERT_FILE` instead; TLS verification stays enabled.
Next children use a 1280 MB heap ceiling and the browser a 1200×800 viewport.
The disposable app uses `next dev --webpack`: the default Turbopack run on
Ubuntu exceeded the unchanged 3072 MB process-tree cap (3313 MB, exit 137).
Webpack keeps compilation in the capped Node heap; the same auth, API and
globe assertions run locally and in CI, with no retries or skipped tests.
The app copy retains proxy, auth and API routes. No job/API requests are mocked.
Smoke opens a card/drawer, changes Applied, verifies it after reload and a real
detail GET, then verifies the globe SQL snapshot and visible WebGL canvas.
Map styles/tiles use the existing public Carto CDN and require network access.
Globe controls must become visible within 30 seconds to allow cold CDN tiles
and software WebGL initialization; an unready globe still fails the smoke.

CI runs the same capped runner on Ubuntu 24.04 with Docker and pinned CLI.
It excludes services unrelated to auth/REST/SQL/mail to fit the runner budget.
RSS includes Node/Next/Chromium; it does not measure Docker daemon/container RSS.

References: [Playwright authentication](https://playwright.dev/docs/auth),
[Supabase CLI config](https://supabase.com/docs/guides/local-development/cli/config),
[Mailpit API](https://mailpit.axllent.org/docs/api-v1/).
