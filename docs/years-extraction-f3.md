# YEARS F3 implementation receipt

Status: IMPLEMENTED; handed back for review, PostgreSQL runtime parity, and exact-head CI.
PR: https://github.com/EtanHey/jobRadarCoach/pull/502
Parent: d14d4d69bcc64a9a97406c1bc6bbd5a6f241a3cd

## Change

Use one explicit number/range + years + experience frame in mandatory context. Reject complex tenure before fallback can expose specialist experience. Optional headings are matched across the whole heading. Requirements/must-have frames take precedence over unscoped applicant prose; disagreeing minima in the selected scope abstain. Numbered/lettered tenure lists and decimals abstain. F2 normalization remains identical and every retained quote is a contiguous source substring.

The TS extractor, Python reference/generator, and generated migration 0039 share the grammar and decision sequence. The SQL function interface, privileges, technology extraction, and future-write-only behavior remain unchanged. No production service, DB, migration application, or backfill was touched.

## Executed evidence

- Earlier 20 cases: 9 correct known, 11 null, **0 wrong-known**.
- Reviewer 15 new cases: 8 correct known, 7 null, **0 wrong-known**.
- Ten additional complex cases below: 1 correct known, 9 null, **0 wrong-known**.
- Node test suite: **241 passed, 0 failed** (233 synthetic fixtures plus 8 existing metadata tests).
- Pure-Python unittest: **2 passed**, including all 233 fixture outputs and SQL generation/contract checks.
- TS/Python reference quote parity: **994/994**, including all 658 frozen snapshot descriptions. All returned quotes are contiguous source substrings.
- Generated SQL is byte-identical to `generate()` and uses the shared predicates, Unicode normalization, and unchanged privilege contract. This is source/model evidence. **Actual PostgreSQL/TS runtime parity was not executed** under the pure-Python-only constraint; the existing DB tests remain available for the lead's permitted runtime gate.
- `git diff --check` passed. No Vitest, build, Docker, installs, or production operations.

One nice(10) tsx test process performed every TS check. An earlier launcher attempt failed with ERR_MODULE_NOT_FOUND before importing the extractor because the runner file was written relative to the wrong directory. Thus there were two launcher invocations, one test-running process. Every Python check ran under nice(10). No simultaneous test runners were used.

## Gold and coverage

The required gold evaluator ran on all 658 predictions with no missing or extra IDs; only years_min was predicted.

| Version | Known | Correct | Wrong-known | Correct / 542 gold-known |
|---|---:|---:|---:|---:|
| Frozen baseline | 444 | 402 | 42 | 74.2% |
| Incoming F2 | 443 | 441 | 2 | 81.4% |
| F3 | 162 | 162 | 0 | 29.9% |

Coverage drops **51.5 percentage points from F2**; known predictions fall by 281. Of F2's 441 correct known values, 281 now abstain. There are 380 abstentions on gold-known rows.

There are **zero baseline-correct to wrong-known changes**, including baseline-null correct results. However, **266 frozen-baseline correct known values become null**. If “zero baseline-correct regressions” includes abstentions, that gate is **NOT met**. This receipt does not relabel that coverage loss as a pass. Strict abstention preserves precision at substantial coverage cost.

32 old fixture expectations and 5 direct assertions now expect null because the lead explicitly replaced complex-clause interpretation and action-only phrases with abstention. No fixture was removed. New cases cover all 15 reviewer inputs, the 10 sentences below, equal/disagreeing minima, must-have precedence, fractional tenure, and embedded second numbers.

## Ten additional cases, frozen before execution

### N01 — result: null

```text
We require 7 (twelve preferred) years of automation experience for this role.
```

### N02 — result: null

```text
Must-have:
8 years of engineering experience (6 with an MSc).
2 years of experience with Nix.
```

### N03 — result: null

```text
Requirements:
9 years of engineering experience / 5 years of experience after doctoral research.
```

### N04 — result: null

```text
Qualifications:
10 years of simulation experience – 6 years of simulation experience with a research degree.
```

### N05 — result: null

```text
Minimum 4 years of platform experience plus extensive work on build systems.
```

### N06 — result: null

```text
At least 5 years of engineering experience; ideally 8 years of engineering experience in observatories.
```

### N07 — result: null

```text
Required:
6 years of software experience with equivalent training accepted in lieu of tenure.
1 year of experience with Meson.
```

### N08 — result: null

```text
Requirements:
Credential paths:
  1) 12 years of robotics experience.
  2) 7 years of robotics experience with a doctorate.
2 years of experience with ROS.
```

### N09 — result: null

```text
Qualifications:
(a) 9 years of embedded experience;
(b) or 4 years of embedded experience with a relevant doctorate.
1 year of experience with Zephyr.
```

### N10 — result: 7

```text
Requirements:
7 years of engineering experience.
Specialist background — nice-to-have:
12 years of experience with plasma simulators.
```

The N10 value 7 is correct: the twelve-year specialist line is under a nice-to-have heading. All other new cases abstain. The synthetic inputs and expected quotes are committed in `ui/tests/fixtures/years-extraction.json`.

## Handoff

Plain-push only; no merge or new reviewer was started. Exact-head CI and PostgreSQL runtime parity remain for the lead. The active worktree is retained for review.
