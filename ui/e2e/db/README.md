# Logged-in tests against local Postgres

Prerequisites: Node >=22.12, Docker running, Supabase CLI **2.116.0**, OpenSSL.
From `ui/`, run `npm ci` and `PLAYWRIGHT_SKIP_BROWSER_GC=1 npx playwright install chromium --only-shell`.
Keep this variable on browser installs to preserve other checkouts' browser caches.
Verified in installed Playwright 1.63.0: `playwright-core/lib/coreBundle.js`
checks `PLAYWRIGHT_SKIP_BROWSER_GC` before `_validateInstallationCache`.
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
**only** this stack's containers/data. DB e2e runs in CI (`ui-tests.yml`,
`logged-in-db`); local Docker/OrbStack is off by design. All local DB commands
require `JRC_LOCAL_DOCKER=1` to run deliberately. The local capped runner stops
any stale project stack before starting. Immediately after start and database reset
it sets `restart=no` on all containers labeled `com.supabase.cli.project=jrc-p12-test-db`, including
stopped containers. After success, failure, SIGINT or SIGTERM it stops the stack,
preserving volume data, and verifies no project container is running. A failed
stop or survivors fail the run and name any survivors; CI keeps its own teardown.
The portable cap wrapper sends SIGTERM only to the root runner and gives it up to
90 seconds to drain work, disable restart policies, back up/stop and scan. Its
SIGINT/SIGTERM paths use the same grace. Only then does it terminate the remaining
process tree, escalating to SIGKILL after 2 seconds. SIGKILL/crashes can
still interrupt cleanup; protected containers will not restart with Docker/OrbStack,
and the next suite cleans up stale containers before starting. A kill before protection
completes after start/reset still requires manual cleanup. On a signal, the runner
waits up to 1.5 seconds for aborted work before scanning and stopping the stack.
A second Ctrl-C waits for teardown to finish.
The HTTPS child also exits on IPC disconnect if its `start-app.mjs` parent dies,
including SIGKILL during startup. After every run, including CI, the runner checks
port 4343. A survivor fails the run; it is stopped only when its PID and start
time (`ps -o lstart=`) match this run's unique receipt and its actual cwd matches
this checkout, so a reused PID is never signalled. Any mismatch or failed lookup
is reported and left untouched. The whole check has one 20 s deadline. It
requires `lsof` and `ps`.
From `ui/`, preserve data while cleaning up with
`JRC_LOCAL_DOCKER=1 supabase stop --project-id jrc-p12-test-db --workdir .`.
This also works in a fresh checkout without `.e2e/db-stack` or its config.
Check for survivors with
`docker ps --filter label=com.supabase.cli.project=jrc-p12-test-db`.

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
The runner builds the disposable app once with `next build`, before
launching Chromium, then serves Next's production request handler in a local
HTTPS server (`next start` has no HTTPS flag). No development compilation runs
alongside the browser. Both phases remain inside the same 3072 MB/600-second
process-tree cap; build/server children have a 1024 MB heap ceiling and one
Next build worker, using the same default bundler as the repository build.
The original hosted dev run exceeded the cap (3313 MB, exit 137); Webpack dev
also exceeded it (3388 MB). The browser retains its 1200×800 viewport.
On a cap failure, the portable runner reports process RSS/names without arguments.
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
