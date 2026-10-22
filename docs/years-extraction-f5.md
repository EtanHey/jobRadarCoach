# YEARS F5 fail-closed receipt

Status: IMPLEMENTED; offline gates pass. Lead review, exact-head CI, and PostgreSQL runtime parity remain pending.
PR: https://github.com/EtanHey/jobRadarCoach/pull/502
Branch: `fix/surge-years-extraction`
Parent: `f26e5e40e8da863bcfc0e90de73aacfd8bd39ab8`

## Behavior

The shared detector admits more years-like mentions than the frame grammar. In mandatory scope, an unmatched mention or remaining tenure outside the sole recognized frame returns null before candidate selection. This includes yr/yrs, YOE, y/o/e, compact or punctuated quantities, full English years, Hebrew שנים/שנות/שנה/שנתיים, and decade/עשור. Residue uses the broad numeric detector too, so compact `8y/o/e` cannot hide behind a missing word boundary. Company and optional-section exclusions still apply.

SIMPLE frames recognize N+ yrs, N yrs exp, N+ YOE, a decade (10), עשור (10), and N שנים ומעלה. The existing full-word experience frame accepts its (YOE) annotation through offset-preserving masking restricted to the position after `experience`; unsupported `8 (YOE)` remains visible to the veto. The period in exp. and line wrapping between quantities and tenure are normalized without moving source offsets. Every returned quote is a contiguous original substring.

Explicit role tenure now outranks specialist tenure even when the role statement appears before a Requirements heading. The same ranking and scope/ambiguity rules apply to full words and shorthand in TS, Python, and generated SQL 0039. Commercial track records and paid professional roles count as role context. R02 returns `7+ yrs`; R04 returns `5 yrs exp`.

The SQL function signature, result shape, technology extraction, ACLs, and future-write-only behavior are unchanged. No production service or database was modified.

## Final verification

| Set | Correct | Abstain | Wrong |
| --- | ---: | ---: | ---: |
| Original reviewer 20 | 14 | 6 | 0 |
| Earlier reviewer 15 | 10 | 5 | 0 |
| F3 ten | 3 | 7 | 0 |
| F4 ten | 10 | 0 | 0 |
| Latest reviewer 20 | 9 | 11 | 0 |

- TS: **355 tests passed**, zero failures/skips, clean exit 0. Includes **347 exact fixture quotes** and eight existing metadata tests. All original 261 fixture expectations remain unchanged; 86 cases were added.
- TS/Python: **1,138/1,138 identical quotes**, covering 75 reviewer cases, 347 fixtures, 58 metadata-corpus inputs, and 658 frozen gold descriptions. This is a comparison count, not a unique-input count.
- Pure-Python unittest: **2 passed**, including fixture quotes, generated SQL equality, shared predicates/frames/normalization, and function/ACL contract checks.
- Gold evaluator: all 658 predictions present; **390 correct / 0 wrong-known / 542 known = 71.9557% coverage**.
- **Zero baseline-correct to wrong regressions**, including gold-null rows. There are **86 baseline-correct known values now abstaining** (85 in F4). The sole changed gold prediction from F4 is an abstention caused by a mandatory “four-year university” mention; the fail-closed rule deliberately does not infer that duration's role.
- Source hashes verified before TS execution and again in the final Python audit. `git diff --check` passed.

The original TS launcher failed before tests with ERR_MODULE_NOT_FOUND because runner creation used the wrong working directory. The authorized replacement passed 352 tests; the subsequent (YOE) masking correction passed the final 355-test run. Etan authorized sequential nice(10) TS processes as a standing rule for this task. All runs were sequential; no concurrent heavy processes, Vitest, build, Docker, or PostgreSQL process was used. Python execution ran under nice(10).

Private reproducible receipts: worktree `docs.local/years-f5/` contains `run.mts`, `reference.json`, `ts-results.json`, `ts-final.log`, `predictions.jsonl`, `audit.py`, `audit.json`, `gold-eval.txt`, and `verified-hashes.json`. Raw gold descriptions stay private.

## Surface ledger

- Entry points — checked TS experiencePhrase, Python experience_phrase, and SQL generator; TS/Python executed, SQL generated-source checks passed.
- Clients — checked existing metadata tests and ui/lib/server.ts list_metadata schema/projection; experience stays string-or-null.
- Providers — checked shared grammar and generated 0039 equality; no actual PostgreSQL execution is claimed.
- Contracts — checked exact source quotes, unchanged JSON keys, immutable/security-invoker signature, empty search_path, and service_role-only execute grant.
- Reverse states — checked unknown units before/after valid candidates, compact/same-clause residue, optional/company scope, conflicting/descending requirements, and null input.
- Connection modes — offline replay only; hosted DB/cache behavior and migration application were not exercised. Cached-row refresh remains operator work.
- Docs — this F5 receipt supersedes F4 calibration behavior; earlier receipts remain historical evidence.

Lead owns review, CI, merge, deployment, and runtime SQL verification. Plain-push only; retain the active worktree for review.
