# YEARS-2 fail-closed formats

Status: F1 IMPLEMENTED; local gates passed for PR #512. The F1 receipt below
supersedes the original packet's counts and preference/collective behavior.
SQL runtime verification remains a CI/lead gate; no migration was applied locally.
Base: `0ce4156` on `origin/master`.

## Behavior

The broad tenure detector now sees compact `4-6y` / `5y+` and label-first
`Exp: 5+`, `Experience: 4-6y`, `YOE: 5`, and
`Professional experience (YOE): 6`. These are deliberately unsupported frames:
in mandatory scope they return null, blocking a lower specialist requirement
both before and after them. Existing detection also covers `3yrs+`.

YOE annotations and higher parenthesized preferences are masked only after a
complete frame. A YOE parenthesis followed by a colon stays visible as a label.
Masking preserves source offsets and cannot turn an interrupted frame into a
supported requirement. F3 N01 therefore abstains. The broad detector also sees
interrupted numeric tenure, so those clauses cannot escape the fallback veto.

Employer subjects and combined/collective/cumulative team or group experience
are excluded. Candidate experience managing a team remains eligible. An added
unquantified work/experience requirement introduced by `plus` vetoes the scalar
minimum, resolving F3 N05.

The shared grammar, TS extractor, Python reference, and SQL generator use the
same sequence. New migration `0040_years_compact_formats.sql` replaces only the
function and its existing ACLs, with no row updates or schema changes. Migration
0039 is byte-for-byte unchanged. Existing cached rows require an operator-owned
backfill; this packet changes future description writes only.

## Verification

- Frozen reviewer set: 95 cases, **49 correct / 46 abstain / 0 wrong-known**.
- Gold: all 658 predictions present; **390 correct / 0 wrong-known / 542 known**,
  exact coverage **71.9557195572%**, above 71.9% and unchanged from the parent.
- Correct-to-wrong: **0** versus both the parent and frozen gold baseline.
  No parent-correct gold value became an abstention.
- TS/Python quote parity: **1,244/1,244** comparisons, comprising 95 reviewer
  inputs, 433 fixtures, 58 metadata-corpus inputs, and 658 gold descriptions.
  Every non-null quote is a contiguous original substring.
- Pure-Python unittest: **2 tests passed**, including all 433 exact fixture
  quotes, generated 0040 equality, grammar, function, and ACL checks.
- Existing Node test suite via `nice -n 10 npx --no-install tsx --test
  --test-reporter=dot .../ui/tests/job-metadata.test.ts`: **441 passed**
  (433 fixtures and eight metadata tests), exit 0.
- Both SQL runtime test paths now apply 0039 then 0040 and reapply 0040. The
  dedicated local-Postgres test also compares all fixture JSON before/after
  reapplication. The Ubuntu PostgREST suite consumes all 433 shared fixtures.
  Neither database path was executed locally in this packet.

Five legacy fixture expectations intentionally become null: the four interrupted
frames at U04, F3 N01, F4-10, and `5+ years (8 preferred) of ...`, plus F3 N05.
This reduces reviewer correct counts by two while eliminating all six remaining
wrong-known outputs. Added 66 prepared regressions and the 20 frozen recheck3
inputs; none of their expectations was weakened after execution.

An initial fixture-edit helper failed while reading a multiline fixture and made
no changes. The initial TS/Python gates exposed a missing
`We are a company` employer exclusion. After correcting that subject rule, the
final TS and Python gates passed. TS processes were sequential under nice(10);
Python checks also ran under nice(10). No Vitest, Docker, database process,
production-service action, build, or package installation ran locally.

Private reproducible inputs and outputs remain under
`docs.local/plan/2026-10-22-triage-fixes/surge/YEARS2-receipts/` in the root
checkout (`run.mts`, `ts-results.json`, `predictions.jsonl`, `audit.py`, `audit.json`).
Gold descriptions are not committed.

## Surface ledger

- Entry points — Checked: `experiencePhrase`, `experience_phrase`, and SQL
  `posting_list_metadata`; TS/Python executed, SQL generated-source verified.
- Clients — Checked: the shared fixture suite and PostgREST list test driver;
  both consume the same quotes, and the DB suite runs after 0040 reapplication.
- Providers — Checked: shared JSON grammar and generated 0040 equality; actual
  PostgreSQL execution remains pending CI.
- Contracts — Checked: string-or-null quotes, contiguous source offsets,
  immutable/security-invoker function, empty search path, and service-role ACLs.
- Reverse states — Checked: unsupported formats before/after valid requirements,
  same-clause residue, optional scope, employer/aggregate subjects, and nulls.
- Connection modes — Checked: offline replay and static upgrade/reapplication
  wiring; no hosted database or production cache was modified or verified.
- Docs — Checked: historical `years-extraction-f5.md`; this receipt supersedes
  its preference-masking and migration-generation behavior.

## F1 final correction

The collective-tenure exclusion previously discarded an entire mixed clause,
including applicant years, allowing a lower specialist frame to win. It now
removes only a recognized combined/collective/cumulative team tenure frame for
the exclusion check. Any remaining tenure makes the entire result null,
including an already selected specialist result. The TS, Python, and generated
0040 implementations use the same fixed team-frame grammar. This implements
the lead's abstention option for mixed clauses in either ordering.

Interrupted higher preferences are admitted only after an immediately adjacent
Requirements / Required qualifications / Minimum qualifications heading and
an explicit `At least N` or `We require N` prefix. The ordinary frame and all
existing ambiguity checks must still pass after masking. This restores U04 and
F4-10 while keeping the other 93 frozen outputs identical to `588d6ca`, including
F3 N01. YOE annotations still cannot create frames. Lower preferences,
qualification alternatives, compact unsupported tenure, and optional scope
retain their guards. Quotes remain contiguous substrings of the original input.

Executed sequentially, using one `nice -n 10 npx --no-install tsx` replay followed
by pure-Python parity and unittest checks:

- Reviewer twenty: **7 correct / 13 abstain / 0 wrong-known**. Both complete
  mixed-clause reproducers are committed fixtures expecting null.
- Original 95: **51 correct / 44 abstain / 0 wrong-known**. Exactly U04 and
  F4-10 changed, both restored to correct; zero master-correct regressions.
- Gold: **390 correct / 268 abstain / 0 wrong-known**, all 658 inputs replayed.
  Known-value coverage is **390 / 542 = 71.9557195572%**.
- Exact TS/Python quote parity: **1,284 / 1,284**, comprising 20 new cases,
  95 original cases, 453 shared fixtures, 58 corpus inputs, and 658 gold inputs.
- Pure-Python unittest: **2 passed**, covering all 453 fixture quotes plus
  generated SQL equality and function/ACL contracts. Twenty fixtures were added;
  only the two authorized regression expectations changed.
- Migration 0039 SHA-256 remains
  `7737a907602990f83bb4a4a436cf8e96fb76a767982549cb736a9d3fa16b6f87`.
  Migration 0040 was regenerated in place and matches the generator exactly.

Private replay inputs, assertions, outputs, parity audit, and source hashes are
under root `docs.local/plan/2026-10-22-triage-fixes/surge/YEARS2-F1-receipts/`.
No Vitest, Docker, synthetic load, database process, or production service
operation ran. SQL runtime parity and hosted migration application remain
unverified for F1 and belong to the lead's CI/application gate.
