# Job Radar Coach UI

Run `npm ci` and `npm run dev` from this directory. Production builds use `npm run build` and `npm start`. Runtime database setup and deployment are documented in the repository setup guide.

The authenticated list API accepts `GET /api/jobs?filter=all&availability=all&limit=100&ids=<comma-separated UUIDs>` for at most 100 IDs per request. This lookup refreshes retained visit cards even after their status or availability excludes them from New for me. List consumers batch only missing retained IDs; the globe hydrates its retained list and globe IDs from the complete snapshot. Failed refreshes keep the previous view with a warning. Explicit status edits in the current tab still remove New for me cards.

Run the synthetic two-context regression with `GLOBE_QA_URL=http://127.0.0.1:<fixture-port> GLOBE_QA_OUTPUT=<evidence-dir> <run-suite-capped.sh> browser-tests/retained-card-status.mjs 3072 120` using the shared `docs.local/tools/run-suite-capped.sh` wrapper, one headless-shell suite at a time, against the isolated app created by `scripts/prepare-globe-fixture.mjs`. It intercepts API requests and SSE; it does not verify hosted database or live realtime delivery.
