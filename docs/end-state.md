# Job Radar Coach — end state

> Owner decision updated 2026-09-10. This supersedes the 2026-09-07
> Mac/Kubernetes topology. Change the target only through a new dated owner
> decision.

## Product

Job Radar Coach is a private, single-owner job-search dashboard and data
pipeline. It collects public postings, ranks them against an evidence-bounded
professional profile, tracks the complete application pipeline, and helps the
owner find both new jobs and older strong matches that still deserve action.

The product remains open source: another user can deploy their own isolated
Supabase project, Vercel dashboard, cloud scraper, and private profile. No
personal profile, row export, credential, or deployment secret belongs in Git.

## Standalone topology

| Component | Runs on | Responsibility |
|---|---|---|
| Dashboard | Vercel | Next.js owner UI and authenticated server API |
| Data and Auth | Hosted Supabase | Postgres, owner identity, access controls, and backups |
| Fetcher | GitHub-hosted Actions | Python fetching, validation, liveness checks, and raw posting persistence without LLM calls |
| Scheduler | GitHub Actions | Native workflow schedule at minute 17 every six hours UTC |
| Extractor and scorer | Owner's local CLI | Bounded LLM work and validated persistence through the hosted database URL |
| Generic agent | DialogKit, separate project | Reusable text/voice conversation, tools, and rendered components |

The Mac may be off while cloud fetching runs. It is required only when the owner
chooses to run local extraction or scoring. Job Radar Coach has no canonical
Kubernetes, LiveKit, Tailscale, or embedded-agent runtime.

## Delivery state

The GitHub cloud workflow contains the default native schedule. The optional
Supabase dispatcher must remain disabled while that schedule is active. Source
is not live proof. The release is complete only after a scheduled request
produces a GitHub run, attempts every configured source under its bounded budget,
and persists fresh hosted rows while the Mac is off.

The local extractor and scorer are implemented as bounded CLI jobs. Their hosted
database cutover, unattended orchestration, and durable end-to-end receipts are
unfinished, so they remain explicit owner-run commands.

Vercel deployment, Supabase import, Auth configuration, owner enrollment, and
live behavior each require their own operational receipt. A merged PR or healthy
service does not establish the next layer.

## Data and semantic ownership

Hosted Supabase is runtime truth:

- `postings` stores source identity, URLs, job metadata, raw descriptions,
  observation time, and liveness.
- `posting_extractions` stores structured fields derived from a posting.
- `posting_scores` stores score, reasons, labels, model metadata, and the exact
  validated scoring payload.
- `posting_status` stores current state; `posting_status_history` records every
  transition.
- `application_history` stores the owner's professional application context.
- `profile` stores search preferences and the safe professional projection.
- `visits` and `heartbeat` support product recency and hosted health contracts.

The status pipeline is:

`new → seen → worth_checking → applied → screen → interview_technical →`
`interview_final → offer → contract`, with `rejected`, `archived`, and
`not_relevant` as terminal side branches. Backward corrections are allowed and
every transition is timestamped. Rejection reasons remain verbatim free text.
`rejected` means the employer declined; `not_relevant` means the owner ruled out
the role, and only the latter is taste evidence.

Job Radar Coach owns these facts and exposes them through a validated,
authenticated semantic API/configuration. Models may phrase responses, but code
owns posting selection, status rules, exact URLs, filters, authorization, and
write validation.

## Model boundary

Cloud scraping performs no model calls. Local extraction and scoring may send
only the explicitly selected professional projection: skills, ratified depth,
tenure, positioning, and public-safe project facts. People, connectors,
prohibited-claim lists, private paths, and nested ownership exclusions never
enter a model request; they remain local guards.

Professional depth distinguishes `hands-on`, `directed-AI`, and
`studied-with-AI`. Values require explicit owner ratification. Missing depth is
unknown, and recent AI-directed work does not erase confirmed hands-on work.
Application history is context, never a company-wide block or invented
cooldown.

Model output is untrusted until the repository validates its closed schema,
evidence identifiers, semantic constraints, and persistence result. A failed
validation must not produce a complete score row.

## DialogKit boundary and preserved owner design

DialogKit is the decoupled generic agent layer. It may call Job Radar's semantic
API, but it does not own job facts, ranking policy, profile truth, or status
writes. Job Radar does not own generic voice transport or conversation runtime.

The 2026-09-09 owner design remains a DialogKit-facing product requirement:

- Delivery order is Job Radar search, then a grilling mode that improves both
  search preferences and claim confidence, then decoupled DialogKit, then the
  public portfolio mini-me.
- Search conversations can render a job card with exact open and detail actions
  that the agent may also invoke; resolved cards may collapse into transcript
  history.
- Grilling can propose evidence/profile changes with explicit confirmation and
  an individually undoable result. Nothing auto-applies.
- An unresolved component stays visible until the owner resolves it; its
  confirmed state joins the transcript before the next agent turn.
- Profile changes are proposed from patterns across evidence, not silently
  inferred from one rejection.
- The future public mini-me is voice-first with text fallback and explicit
  résumé-download and GitHub actions; it is outside this repository's runtime.

The legacy embedded agent/LiveKit integration is preserved as legacy evidence
until the separately owned DialogKit replacement map and runtime are proven. It
is not converted in place and is not part of standalone setup.

## Security and operations

- Supabase browser roles have no table or routine access. Vercel server routes
  authorize the allowlisted owner before using the server-only service role.
- Passkey relying-party settings and callback origins match the exact production
  HTTPS origin. Missing configuration fails closed with private, no-store
  responses.
- The cloud fetcher uses only public, credential-free job sources. Its database
  URL remains in the GitHub repository secret store.
- Backups are encrypted, excluded from Git, hashed, count-checked, and restored
  into a disposable database before a production import or destructive change.
- Disable and rollback paths exist for the cloud schedule. No cleanup removes a
  shared extension, externally managed credential, or unverified last backup.

## Completion criteria

The standalone migration is complete when all of these are proven together:

1. The owner can authenticate to the production Vercel hostname, read hosted
   data, and perform authorized mutations; anonymous and non-owner access fail.
2. The native GitHub schedule causes a successful cloud fetch while the Mac is
   off, and the receipt ties configured sources to newly persisted hosted rows.
3. The local CLI extracts and scores hosted unprocessed rows with validated,
   reviewable receipts and no private-context leakage.
4. Backup restore, schedule disable/rollback, Auth recovery, and deployment
   rollback have each been rehearsed without losing the retained source copy.
5. Any DialogKit integration consumes the Job Radar semantic contract as a
   separate client and has its own runtime proof.
