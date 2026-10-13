# Job Radar Coach UI

Run `npm ci` and `npm run dev` from this directory. Production builds use `npm run build` and `npm start`. Runtime database setup and deployment are documented in the repository setup guide.

The authenticated list API accepts `GET /api/jobs?filter=all&availability=all&limit=100&ids=<comma-separated UUIDs>` for at most 100 IDs per request. This lookup refreshes retained visit cards even after their status or availability excludes them from New for me. List consumers batch only missing retained IDs; the globe hydrates its retained list and globe IDs from the complete snapshot. Failed refreshes keep the previous view with a warning. The board's new-roles poll uses the same endpoint with `since=<first_seen_at>` (strictly newer, up to `limit=101`; `ids` and `since` are exclusive) and counts the cards Show would add with the board's own view filters and duplicate grouping. Explicit status edits in the current tab still remove New for me cards.

Run the synthetic two-context regression with `GLOBE_QA_URL=http://127.0.0.1:<fixture-port> GLOBE_QA_OUTPUT=<evidence-dir> <run-suite-capped.sh> browser-tests/retained-card-status.mjs 3072 120` using the shared `docs.local/tools/run-suite-capped.sh` wrapper, one headless-shell suite at a time, against the isolated app created by `scripts/prepare-globe-fixture.mjs`. It intercepts API requests (the board has no live sync; refreshes go through the "N new roles · Show" pill) and does not verify the hosted database.

Globe debug datasets require the build-time opt-in `NEXT_PUBLIC_QA_DATASETS=1`; `scripts/prepare-globe-fixture.mjs` enables it for both dev and production fixtures, while real production builds leave it unset.

Company logos resolve in one order (`lib/company-logos.ts`): override map (`lib/company-logo-overrides.ts`), curated catalog (`public/companies`), Logo.dev when `NEXT_PUBLIC_LOGO_DEV_KEY` holds a publishable `pk_` key (Vercel env, or a gitignored `ui/.env.local` locally), then initials. Pin a wrong Logo.dev match in the override map.

The Python suite includes a real DB-backed list/detail contract through disposable PostgREST. After `npm ci` here, set `DATABASE_URL` to a disposable local PostgreSQL server and `JOBRADAR_POSTGREST_BIN` to the PostgREST executable, then run `uv run --group test pytest test_support/test_ui_list_database.py` from the repository root. CI installs a pinned binary and requires this contract without skips.

Migration 0024 generates compact list metadata for existing and new descriptions. The lead must apply it before deploying the UI that selects `list_metadata`; it rewrites the postings table while backfilling. Full descriptions remain on detail reads.
