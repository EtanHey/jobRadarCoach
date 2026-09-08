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
The live voice LLM is always a local OpenAI-compatible chat endpoint, `LLM_BASE_URL`: Ollama by default
(portable); Etan's instance points it at `mlx_lm.server` (faster on Apple Silicon). `codex exec` cannot hold a
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

## Owner amendments — 2026-09-07

- Luna receives an explicitly selected professional projection only: skills, ratified depth, tenure,
  positioning, and public-safe project facts. People, connectors, prohibited-claims
  lists, and nested ownership exclusions never enter a cloud-brain request; they remain local guards.
- Professional depth supports `hands-on`, `directed-AI`, and `studied-with-AI`. Values require Etan's
  explicit ratification. Empty/unset depth is not evidence of no knowledge, and recent AI-directed work
  does not erase earlier confirmed hands-on depth.
- Application history is a separate future table and fit input. A past company is context, never a
  company-wide hard block or invented fixed cooldown; `posting_status` remains the current posting state.
- CLIProxyAPI is permitted only for a future `BRAIN=codex` spike after logical lane 2. It is not an
  approved transport for Claude or Gemini and is not claimed installed or verified.
- Voice sessions (Etan, 2026-09-07 evening): one LiveKit room per web client (Mac tab, phone tab). Mic is
  sticky push-to-talk: tap opens, tap closes; opening the mic on any client closes any other open mic for the
  same user. No always-open mic. `ui` and `livekit` are the only Services; Jobs/CronJobs get none.

## Owner amendment — 2026-09-08: voice is how the profile is maintained

Etan, after using the UI: "once we finish setting up the livekit side it'll be much more useful as I'll be
able to word out why some things dont match and some do, with the nitpicks and the ai would be able to find
what to edit in the prefrences instead of me giving short answers to the reject and steering filtering too much."

This is the product thesis. It has three consequences:

1. **Rejection reasons are stored verbatim**, as the user said them, in free text. Never as a category from a
   fixed list. The accumulated reasons are the corpus the agent reasons over; a label destroys the signal.
2. **`update_profile` is not a setter.** The voice tool accepts what the user actually said and the model
   derives which preference rows that implies. It must state the intended change back to the user in words
   before writing. A tool that takes (field, value) recreates filter-steering by voice and misses the point.
3. **Guard against overfitting.** The agent proposes a preference change only after it observes a PATTERN
   across several rejections, names the pattern aloud, and every edit it has made is listed, attributed, and
   individually undoable in the profile drawer. A profile that silently narrows until good roles stop
   appearing is the failure mode this rule exists to prevent.

### Three tiers, not one (Etan, 2026-09-08)

"Maybe even after a lot of patterns emerge it brings it up to a astra/sol model to give it suggested
profile/settings edits, then it goes over them with me?"

| Tier | Who | Job |
|---|---|---|
| Live | local model (Ollama/MLX), in the voice session | capture the reason verbatim, notice a pattern, say it out loud, read proposals back. Nothing more — this is deliberately small so the voice side stays free and fast. |
| Advisor | a strong model via the BRAIN adapter (codex: gpt-6-astra / gpt-5.6-sol), batch | a fourth Job alongside extractor and classifier. Weekly or on demand. Reads the whole corpus — verbatim rejection reasons AND what was saved/applied, not the profile alone — and DRAFTS proposed profile edits. Each proposal must cite the specific postings and reasons it came from. It writes proposals to a table; it never writes the profile. |
| Review | Etan | goes over proposals by voice or in the profile drawer, accepts or rejects each one individually. Nothing auto-applies, ever. |

The advisor tier is also where overfitting gets caught: a bad suggestion shows up as a proposal with thin
evidence attached, instead of a silent narrowing noticed weeks later when good roles stopped appearing.

### Status is a pipeline, not triage (Etan, 2026-09-08)

Etan, comparing against ScoutMole: "she also has more options for once you want to set a status on a job."
Her menu: שווה בדיקה (worth checking) · שלחתי קו"ח (sent CV) · ראיון ראשוני (initial interview) ·
ראיון טכני (technical interview) · חוזה (contract) · ארכיון (archive) · לא רלוונטי (not relevant).

Supersedes the earlier `new → seen → saved | applied | rejected` enum. Etan already tracks these stages by
hand in his Obsidian Career Hub table; the app should carry them so it replaces that table, and the stages
feed the application-history table built in lane 2H.

New `posting_status.status`:
`new` → `seen` → `worth_checking` → `applied` → `screen` (HR/recruiter call) → `interview_technical` →
`interview_final` → `offer` → `contract`, with the terminal side branches `rejected` (reason REQUIRED,
stored verbatim), `archived`, and `not_relevant`.

Rules: one status per posting, forward moves are ordinary edits and backward moves are allowed. Every
transition is timestamped in application history so the UI can show "applied 6 days ago, no reply." The
voice agent's `set_status` tool takes any of these. `rejected` and `not_relevant` are distinct: rejected
means they said no, not_relevant means Etan ruled it out — and only the second is taste signal for the
advisor tier.
