# Optional Supabase cloud scrape dispatcher

The default scheduler is the native `schedule` trigger in
`.github/workflows/cloud-scrape.yml`. This package is retained as an optional
operator-applied Supabase Cron alternative. Do not activate this route while
the native GitHub schedule is active. Disable one scheduler before enabling the
other so a six-hour interval cannot dispatch duplicate runs.

Do not execute this package until the hosted release owner authorizes creating
the schedule and sending its first request.

The scheduled command calls a private database function every six hours at
00:00, 06:00, 12:00, and 18:00 UTC. The function reads a GitHub credential from
Supabase Vault at execution time and queues a `workflow_dispatch` request for
`EtanHey/jobRadarCoach`, workflow `.github/workflows/cloud-scrape.yml`, branch
`master`. GitHub Actions concurrency prevents overlapping scraper runs.

## Credential precondition

Create a fine-grained GitHub credential that can access only the
`EtanHey/jobRadarCoach` repository and has **Actions: write**. Store it with the
Supabase Vault UI under the exact name `job_radar_github_actions_token`. Do not
paste the value into this repository, a SQL file, or shell history. The install
transaction aborts unless exactly one non-empty secret with that name exists.

Vault supplies the credential at runtime, so `cron.job.command` and Cron run
logs contain only `select scheduler_private.dispatch_cloud_scrape();`. `pg_net`
must briefly place outbound headers in its unlogged request queue; the installer
revokes queue and Vault-view reads from `public`, `anon`, `authenticated`, and
`service_role`. Database owners remain privileged and must be treated as secret
administrators.

## Operator actions

Run `install.sql` as the Supabase database owner with stop-on-error behavior.
It enables `pg_cron` and `pg_net`, installs the dispatcher, and creates or
updates the named schedule. Applying the file creates a real schedule, so source
review alone is not authorization to run it.

To pause dispatches while retaining the function and named job, run
`disable.sql`. To remove the named job and dispatcher, run `rollback.sql`.
Rollback intentionally leaves extensions, the private schema, and the Vault
secret in place; revoke the GitHub credential and remove its Vault entry through
the secret-management procedure if the integration is retired.

Cron success proves that `pg_net` accepted a request into its queue. GitHub's
dispatch response proves acceptance by GitHub. Neither proves that the workflow
completed or that fresh rows were persisted; durable hosted outcome receipts
belong to the next slice.

References: [Supabase Cron](https://supabase.com/docs/guides/cron),
[Supabase Vault](https://supabase.com/docs/guides/database/vault), and
[GitHub workflow dispatch](https://docs.github.com/en/rest/actions/workflows#create-a-workflow-dispatch-event).
