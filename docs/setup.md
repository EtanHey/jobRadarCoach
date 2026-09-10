# Standalone setup

Job Radar Coach uses a Vercel dashboard, hosted Supabase data and authentication,
a GitHub-hosted Python scraper, and local CLI extraction and scoring. The
canonical setup does not run Kubernetes, LiveKit, Tailscale Serve, or the legacy
`jrc` runtime.

Repository source, hosted configuration, an accepted cloud request, a completed
workflow, and persisted fresh rows are separate proof layers. Follow the release
gates for the environment you operate; do not infer live behavior from this
guide or from merged source.

## 1. Prepare a protected checkout

Install Git, Python 3.12, Node.js, and the Supabase CLI. The optional local
Supabase workflow in step 3 also requires Docker Desktop or another supported
container runtime. Then clone the repository:

```zsh
git clone https://github.com/EtanHey/jobRadarCoach.git
cd jobRadarCoach
git config core.hooksPath .githooks
python3 scripts/check_private_files.py --all-tracked
```

Install the Python runtime packages pinned in
[`scraper/Dockerfile`](../scraper/Dockerfile) before running the scraper or
local model jobs. The Codex provider also requires the CLI version pinned by
[`build/install_codex.py`](../build/install_codex.py); use `BRAIN=ollama` when
Codex CLI is not installed.

The hook and audit command reject private runtime files. Keep `profile.yaml`,
`docs.local/`, database exports, `.env` files, credentials, run logs, and backup
artifacts outside version control. Never put raw secrets or private rows in a
commit, PR, issue, CI log, or command argument.

## 2. Validate a private profile

For a new installation, copy the public schema to the ignored path and replace
every example value with truthful data:

```zsh
cp profile.example.yaml profile.yaml
chmod 600 profile.yaml
${EDITOR:-vi} profile.yaml
git check-ignore -q profile.yaml
python3 - <<'PY'
from pathlib import Path
from scraper.database import REQUIRED_PROFILE_FIELDS, build_profile_seed

seed = build_profile_seed(Path("profile.yaml"), Path("scraper/searches.yaml"))
assert set(seed) == REQUIRED_PROFILE_FIELDS
print("profile seed is valid")
PY
```

Keep `safe_radar_projection` as the final indented JSON block. Replace every
example city, claim, evidence identifier, scope, and exclusion. The database
profile becomes runtime truth after seeding or import; later edits to
`profile.yaml` do not overwrite existing rows.

The hosted scraper image deliberately contains no private profile. Seed or
import a complete profile before activating cloud scraping, or the run must fail
closed.

## 3. Develop against local Supabase

Local Supabase remains useful for migration and contract tests. It is not the
production topology.

```zsh
supabase start
supabase migration up --local
supabase test db
```

Never reset a database that contains the only copy of user data. Apply pending
migrations in order and test them on disposable data before using a hosted
project.

For a credential-free local fetch to JSONL, with model annotation disabled:

```zsh
python3 scraper/harvest.py --jsonl --no-annotate \
  --profile profile.yaml --max-pages 1 --jd-fetch-cap 3 \
  --sources comeet,greenhouse,lever,workable
```

LinkedIn guest search is the always-on source; `--sources` enables the four
reviewed public ATS adapters. The scraper uses no login, cookies, browser
profile, stored source credentials, or metered scraping API.

## 4. Prepare hosted Supabase

Use a dedicated hosted project. Before the first import or any destructive
schema change:

1. Create an encrypted private backup outside the checkout.
2. Record table counts and artifact hashes without printing row contents.
3. Rehearse the ordered restore into a disposable database.
4. Keep the source backup until hosted counts, constraints, triggers, and access
   controls have been verified.

Link the Supabase CLI only after confirming the project identifier. Review the
target again before the operator applies repository migrations:

```zsh
supabase link --project-ref <project-ref>
supabase db push --linked
```

Do not place database passwords in the command. Supply them through the approved
secret manager or interactive prompt. Migration `0010_hosted_access.sql` makes
the browser roles fail closed; the dashboard reaches data only through its
authenticated server routes and server-side service credential.

Create the single owner account before enabling recovery. Configure the exact
production HTTPS origin as the Supabase site URL and passkey relying-party
origin. Enroll and verify the primary owner passkey in the intended browser,
then verify the same-browser recovery callback. Do not enable public sign-up or
assume that an Auth setting proves the ceremony worked.

## 5. Configure the Vercel dashboard

Deploy the `ui` application through Vercel's Git integration. Configure these
environment contracts in Vercel; never commit their values:

| Variable | Exposure | Purpose |
|---|---|---|
| `SUPABASE_URL` | server | Hosted Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | secret, server only | Server-route database access |
| `NEXT_PUBLIC_SUPABASE_URL` | browser | Hosted Auth URL |
| `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` | browser | Supabase publishable Auth key |
| `JRC_OWNER_USER_IDS` | server | Comma-separated allowlisted owner UUIDs |
| `UI_ORIGIN` | server | Exact production HTTPS origin |
| `JRC_OWNER_RECOVERY_ENABLED` | server | Explicit recovery gate |
| `JRC_OWNER_RECOVERY_EMAIL` | secret, server only | Existing owner recovery address |

Missing or malformed Auth configuration intentionally returns a private,
non-cacheable unavailable response. After deployment, verify signed-out denial,
owner login, non-owner denial, data reads, mutations, and recovery on the exact
production hostname. A successful Vercel build is not this behavioral proof.

For local UI development:

```zsh
npm --prefix ui ci
npm --prefix ui run dev
```

Use a local ignored environment file with synthetic or disposable values. Never
expose the service-role key through a `NEXT_PUBLIC_` variable.

## 6. Configure cloud fetching

The manual workflow is
[`cloud-scrape.yml`](../.github/workflows/cloud-scrape.yml). It runs the Python
scraper on GitHub-hosted Linux, disables LLM annotation, bounds network work,
persists through `DATABASE_URL`, and prevents overlapping runs.

The Supabase package in
[`supabase/scheduling/cloud_scrape`](../supabase/scheduling/cloud_scrape/README.md)
dispatches that workflow every six hours through `pg_cron`, `pg_net`, and a
Vault-held repository-scoped GitHub token. Configure only:

- GitHub Actions secret `DATABASE_URL` for the hosted database.
- Supabase Vault secret `job_radar_github_actions_token`, restricted to this
  repository with Actions write.

The scheduling source is merged, but activation still requires release-owner
approval and live verification. Follow its installer, disable, and rollback
instructions. Do not paste the token into SQL, shell history, or Cron commands.

The first release proof must connect one Cron invocation to the `pg_net`
response, GitHub run, cloud receipt, source attempts, and newly persisted hosted
rows. A queued HTTP request or green workflow alone is incomplete.

## 7. Run local extraction and scoring

LLM work stays on the owner's machine. Load `DATABASE_URL` through the approved
secret manager, choose an implemented local provider, and run bounded jobs:

```zsh
BRAIN=codex python3 -m extractor.job --limit 10 --timeout-seconds 120
BRAIN=codex python3 -m classifier.job --limit 10 --timeout-seconds 120
```

`BRAIN=ollama` is also implemented. Both jobs validate structured model output
before persistence and return nonzero on failed work. The CLI code exists, but
the hosted cutover, scheduling, unattended pickup, and end-to-end receipt are
unfinished. Run it manually and inspect its counts until those gates ship.

Only the explicitly selected safe professional projection may enter a model
request. People, connectors, prohibited-claim lists, private paths, and nested
ownership exclusions stay local as validation guards.

## 8. Validate changes

Run the affected suites before proposing a change:

```zsh
python3 -m pytest -q scraper extractor classifier \
  supabase/scheduling/cloud_scrape/test_schedule.py \
  scripts/test_check_private_files.py
python3 -m ruff check \
  --per-file-ignores 'extractor/test_persistence.py:E402' \
  scraper extractor classifier \
  supabase/scheduling/cloud_scrape/test_schedule.py \
  scripts/check_private_files.py scripts/test_check_private_files.py
npm --prefix ui run test
npm --prefix ui run lint
npm --prefix ui run build
```

Database migrations also require `supabase test db` against a disposable local
instance. A mock suite, source inspection, CI pass, deployment, and real hosted
behavior remain distinct claims.

## DialogKit and legacy integration

DialogKit owns the reusable agent loop, voice/text transport, and rendered
conversation components. Job Radar Coach owns job facts, status semantics,
profile rules, and its authenticated semantic API/configuration.

Do not copy the legacy embedded agent, LiveKit, Kubernetes, or `jrc` setup into
the standalone deployment. Preserve the legacy integration as reference until
the separately owned DialogKit replacement map and runtime are proven. This is
a separation and replacement boundary, not an in-place conversion.
