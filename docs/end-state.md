# jobRadarCoach — end state

> Frozen 2026-09-07 after a 4-round grill (Etan + coachClaude). This is the target every lane builds toward.
> Change it only by a new decision from Etan, recorded here with a date.

## What it is

A self-hosted voice agent that knows your job search: it scrapes postings, extracts and scores them against
*your* profile, and talks to you about what is new **for you** — new since your last visit, minus what you
already heard, opened, saved, applied to, or rejected. It may also resurface a job you have seen but not
applied to when it strongly thinks you should.

Runs on one Mac for $0: OrbStack's built-in k3s, a local Supabase, Ollama with Metal. Served over your
Tailscale tailnet so it works from your phone outside the house. Open source: others clone it, bring their
own Supabase and their own profile, and run it themselves. Single user, no login.

## Topology

Namespace `job-radar-coach` in OrbStack k3s (`kubectl config use-context orbstack`).

| Pod | Kind | Owner | Notes |
|---|---|---|---|
| `scraper` | CronJob | workers | exists (`k8s/scraper-cronjob.yaml`, image `job-radar:dev`, currently suspended). Must write rows to Postgres instead of JSONL. |
| `extractor` | Job | workers | structured fields per posting, via the `BRAIN` adapter |
| `classifier` | Job | workers | Luna v1 ported: score 0–100 + labels |
| `ui` | Deployment + Service | workers | Next.js + Tailwind + shadcn. API = route handlers (LiveKit token minting, supabase-js). Own Dockerfile. `tailscale serve` in front for HTTPS on the phone. |
| `livekit` | Deployment + Service + ConfigMap | **Etan (D3) — withheld** | self-hosted `livekit/livekit-server` |
| `agent` | Deployment | **Etan (D4) — withheld** | Python, `livekit-agents`, tools below |

Outside k3s, on the Mac, reached from pods as `host.docker.internal` (proven 2026-09-07 with Supabase on 54322):

- Supabase local (`supabase start`): Postgres `:54322`, Studio `:54323`, API `:54321`. Schema lives in `supabase/migrations/`. Later `supabase db push` moves it to hosted.
- Ollama (Metal) — live LLM for the agent (Gemma), and the default batch brain.
- whisper server + Kokoro-FastAPI — STT/TTS as OpenAI-compatible endpoints. Native so Metal does the work; the agent pod stays thin.

Images are built locally with `docker build -t <name>:dev`; OrbStack's k3s uses them directly, no registry.

## Data model (Supabase Postgres)

- `postings` — one row per posting: source, external id, url, title, company, location, remote, seniority,
  stack (text[]), salary, apply_url, posted_at, raw_jd, first_seen_at, last_seen_at, liveness.
- `posting_scores` — per posting: score 0–100, reasons, labels (role_type: frontend|fullstack|ai|voice,
  seniority_match, remote_ok, red_flag_count), brain used, scored_at.
- `posting_status` — per posting: status `new → seen → saved | applied | rejected`, reason (text, required
  on rejected), updated_at. One row, one status column. "seen" = read aloud by the agent OR opened in the UI.
- `profile` — the user's taste as rows (roles wanted, stacks, seniority, remote, locations, salary floor,
  red-flag words, free-text preferences). Also the search terms the scraper runs. **Truth lives here.**
  A gitignored `profile.yaml` only seeds these rows on first run.
- `visits` — `last_visit_at`; "new for me" = `posted_at > last_visit_at` and no status beyond `new`.

Supabase Realtime subscriptions push row changes to the UI (agent marks applied → list updates).

## Brains

One adapter, chosen by env: `BRAIN=ollama | codex | claude | cursor-agent`. `ollama` is the repo default
($0, runs anywhere). Etan's own instance uses `codex` (ChatGPT subscription, `codex exec`); see
`~/Gits/t3code` for how a Codex CLI connection and commit-message generation are wired. The UI has a toggle.
The live voice LLM is always Ollama (an OpenAI-compatible chat endpoint); `codex exec` cannot hold a
conversation.

## Voice agent tools (D4, Etan builds; workers only prepare the SQL functions they call)

- `list_new_for_me()` — ranked unseen postings since last visit.
- `set_status(posting_id, status, reason?)` — writes `posting_status`.
- `update_profile(field, value)` — voice edits the profile rows.
- `open_job(posting_id)` — sends a message over the LiveKit data channel; the mic page opens the tab.
  (Alternative kept in mind: the agent emits a custom button for the user to tap.)

## Open-source rules

- `docs/setup.md` must show: OrbStack + k3s, `supabase start`, Ollama, seeding your own `profile.yaml`,
  choosing a `BRAIN`. Nothing personal is ever committed: `profile.yaml`, `docs.local/`, `.env`,
  `supabase/.env` are gitignored and a guard script fails the commit if they slip in.
- No Telegram. No login. No Effect library. Plain TS + zod at boundaries.

## Lane order for workers (each = one small PR, XS/S)

1. Move `scripts/job-feed` from `~/Gits/coach` into `scraper/`; fix the two `COPY` lines in the Dockerfile;
   personal `references/profile-export.yaml` becomes the seed format, not baked into the image.
2. Schema migration 0001 (tables above) + `scraper` writes rows (psycopg) instead of JSONL; `--jsonl` stays
   as an optional flag. Verify: a CronJob run in the cluster inserts rows visible in Studio.
3. Extractor Job + `BRAIN` adapter (ollama first, codex second).
4. Classifier Job — port Luna (`annotate.py`) prompts; score + labels.
5. `ui` pod: list / detail / status buttons / profile drawer / brain toggle; Realtime; Dockerfile; manifest.
6. `docs/setup.md` + guard script.

Withheld from workers: anything under `k8s/livekit*`, `agent/`, and the mic page's LiveKit client code.
