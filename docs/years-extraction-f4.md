# YEARS F4 calibration receipt

Status: IMPLEMENTED; requested extraction gates pass. Lead review, exact-head CI, and PostgreSQL runtime parity remain pending.
PR: https://github.com/EtanHey/jobRadarCoach/pull/502
Parent: `95c528342942c957911b7fec1dec5b175410eee2`
Branch: `fix/surge-years-extraction`

## Behavior

TS, the Python reference/generator, and generated SQL 0039 now share the English lead grammar, range quantities, numeric-preference masking, and selection predicates. Hyphen/en-dash/to ranges and Hebrew בין N ל-M retain the lower bound. At-least/minimum/or-more frames and supported English number words retain their stated minimum. Higher numeric preferences in parentheses are masked without moving source offsets, including preferences embedded before “years”. Every displayed quote remains a contiguous original-source substring.

Ordinary discipline alternatives (such as C/C++ or Rust) no longer invalidate tenure. Explicit professional/action tenure is admitted again. A trailing “ideally/preferably in/with” domain preference can be ignored only when it contains no number or tenure. Required role/overall frames take priority over specialist frames in the same scope; different minima at the selected priority still abstain. Company-tenure exclusions remain on both sides of a frame. Real qualification alternatives, unresolved multiple frames, optional requirement scope, decimals, and numbered/lettered tenure lists still abstain.

SQL matches the earliest start and then the shared ordered alternatives rather than taking PostgreSQL ARE's longest alternative. The function interface, privileges, technology extraction, and future-write-only migration contract are unchanged. No service, database, deployment, or backfill was touched.

## Executed gates

- Original 20 reviewer cases: 14 correct known, 6 abstentions, **0 wrong-known**.
- Newer 15 reviewer cases: 10 correct known, 5 abstentions, **0 wrong-known**.
- Ten F3 extras: 3 correct known, 7 abstentions, **0 wrong-known**.
- Ten new F4 range/preference sentences: **10 correct**, zero abstentions or wrong-known.
- Final assertion replay: **269 check bodies passed** (261 fixture quotes and 8 metadata checks); zero final failures. Eighteen F3 fixture abstentions and five direct expectations were revised to known values under the calibration ruling. No fixture was removed; 28 new fixtures cover the ten new sentences and eighteen controls.
- Pure-Python unittest: **2 passed**, covering all 261 fixture outputs, generated SQL equality, shared predicates, normalization, and function/ACL/no-backfill contract.
- TS/Python quote parity: **1,032/1,032 comparisons** across 55 gated cases, 261 fixtures, 58 metadata-corpus inputs, and 658 frozen descriptions. This is a comparison count, not a unique-input count. All returned quotes are contiguous source substrings.
- The required gold evaluator ran against all **658 predictions**, with no missing/extra IDs: **391 correct / 0 wrong-known / 542 gold-known = 72.1402% coverage**. Only years_min was predicted; other evaluator fields are out of scope.
- **Zero baseline-correct regressions to wrong**, including gold-null rows. There remain **85 baseline-correct known values that abstain**, down from F3's 266. F3 returned 162 correct; F4 returns 229 more correct values. Frozen baseline returned 402 correct and 42 wrong-known.
- `git diff --check` passed.

The F3 extra file used null to encode its conservative output for N01/N05/N06. For F4 scoring, their semantic minima are explicitly recorded as 7, 4, and 5. N01 and N05 now return those correct minima; N06 still safely abstains. This re-adjudication follows the calibration ruling and is not an unchanged-F3-expectation claim.

## Remaining gold-known abstentions: 151

Categories record the first deciding rejection branch, not a claim that the underlying posting is intrinsically ambiguous:

- Optional qualifier scope: 29.
- Numeric alternative or numeric parenthetical: 28.
- Negated, approximate, or other rejected requirement qualifier: 24.
- No admitted mandatory frame/context: 19.
- Unsupported or incomplete tenure frame: 17.
- Conflicting minima in the selected scope: 16.
- Multiple tenure frames in one clause: 12.
- Alternative qualification route/equivalence: 5.
- Fractional or numbered tenure: 1.

## Ten new sentences (expected minimum)

1. “Requirements: We require 3-6 years of aeronautical engineering experience.” — 3.
2. “Required: 4–9 years of software engineering experience on navigation platforms.” — 4.
3. “You bring six to eight years of professional experience in compiler tooling.” — 6.
4. “דרישות: נדרש ניסיון של בין 4 ל-7 שנים בפיתוח מערכות חלל.” — 4.
5. “We require 5+ years of robotics experience (9 preferred).” — 5.
6. “Required: Seven+ years of development experience (ten+ ideal).” — 7.
7. “At least four years of simulation experience in optical systems.” — 4.
8. “Minimum six years of platform engineering experience is required.” — 6.
9. “You need 3 or more years of embedded engineering experience.” — 3.
10. “Requirements: We require five (eight preferred) years of software engineering experience.” — 5.

Exact newline-preserving inputs and quotes are committed in the fixture file.

## Verification limits and process deviations

All Python execution/checks ran under nice(10). No Vitest, Docker, build, install, PostgreSQL process, or production operation ran. SQL parity is source/generator evidence only; no actual PostgreSQL execution occurred.

There were **two tsx launcher invocations**, not the requested literal one: the first printed READY and exited because stdin closed, before running any checks. The second was the sole test-running persistent nice(10) tsx process. This launcher mistake is a constraint deviation.

The second process initially ran the Node test suite with 267 passing / 2 failing check bodies. One failure exposed the company-tenure suffix exclusion regression; it was repaired in all implementations. The other expectation still required null for “Experience of at least 2 years in software development”; the calibrated expected quote was updated. The same process then imported the actual revised production module under a fresh URL and synchronously replayed every updated test callback using Node assertions: **269 passed / 0 failed**. Its final process exit remains **1** because node:test retains the two historical failures. Thus this is passing final assertion evidence, **not a clean node:test process-exit claim**. Exact-head CI remains required.

Private reproducible receipts are under the worktree's `docs.local/years-f4/`: `run.mts`, `final2.ts`, `final2-tests.ts`, `final2-test-summary.json`, `final2-results.json`, `final2-predictions.jsonl`, `final2-audit.json`, `final2-abstentions.json`, `final2-eval.txt`, and `verified-hashes.json`. Raw gold descriptions stay private.

## Surface ledger and handoff

- Entry points — checked TS experiencePhrase, Python experience_phrase, and SQL generator; local execution for TS/Python, generated-source checks for SQL.
- Clients — checked existing metadata assertions and server list_metadata string-or-null schema/projection; no interface change.
- Providers — checked shared grammar and generated 0039; real PostgreSQL runtime remains for the lead.
- Contracts — checked contiguous quotes, unchanged JSON keys, immutable/security-invoker signature, empty search_path, and service_role-only execute grant.
- Reverse states — checked null input, optional scopes, alternative routes, descending ranges, and conflicts in fixtures.
- Connection modes — offline replay only; hosted DB/cache behavior was not exercised. Existing cached metadata requires separately authorized operator refresh.
- Docs — this F4 receipt supersedes F3's conservative calibration; the F3 receipt remains historical evidence.

Plain-push only; no merge, reviewer launch, PR watch, or polling loop. The active worktree is retained for lead review. Next: lead review plus exact-head CI and real PostgreSQL parity before any deployment.
