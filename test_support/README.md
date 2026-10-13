# Python and database checks

Run `uv run --locked --group test pytest -ra` from the repository root.
The test group includes pytest and the build tools used by the wheel test;
the optional embedding models are not installed.

The `Python and DB tests` workflow runs on every PR and master push with an
isolated PostgreSQL 17 service, pgTAP, Supabase roles, and UTC. It requires
the database instead of silently skipping it. Native extraction and Ollama
proofs remain disabled; macOS Keychain checks skip on the Linux runner.

For full local coverage, set `DATABASE_URL` to a disposable PostgreSQL instance
with pgTAP and the roles bootstrapped in the workflow. The tests create and drop
sibling databases; never point this command at a hosted or production database.
All migrations are smoke-tested through the latest numbered file. Each
SQL contract runs against that latest schema and must emit a complete,
passing TAP plan without skipped assertions.
