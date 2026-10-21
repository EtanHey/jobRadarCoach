# Job Radar pipeline: bounded safety model

Status: P0 fix round 1, ready for lead-routed round 2 review. No PR opened.
Only the specification, local runner, and this evidence document change.

## Run locally

```sh
./spec/tla/check.sh
# Retain raw logs and exact witness configurations in a NEW directory.
TLC_LOG_DIR=/tmp/jrc-tlc-evidence ./spec/tla/check.sh
```

Requires Java, `rg`, and `tlc` on PATH, or `TLC=/path/to/tlc`.
The runner copies the model to a temporary directory and removes only that directory.
It runs the target, four independent current-code invariant checks, and six focused
checks. Expected violations require exit 12 and the exact requested invariant error.
Passing controls require exit 0 and TLC's completion message. Any mismatch fails.
`JrcPipeline_current.cfg` is a base; append `INVARIANT <name>` for a manual run.

## Scope and interpretation

The pipeline is registry → eligible queries → fetch → geography/title filter →
source-ID upsert → visible vacancy groups → liveness checks → displayed alive.
Three boards, four postings, seven posting fixtures, three registry fixtures, and
clock values 0..2 bound the state space. Registry age is MaxAge=1 or 2; one fixture
disables Workable. Eligible fetches succeed or fail independently. Upserts explore
every posting order. Posting 4 is a different employer in London with a rejected
title, so geography's foreign negative control does not depend on title matching.

Postings 1/2 are Comeet rows with different external IDs and one employer.
Fixture inputs are already normalized. Posting 3 has another title, R2, and the
same JD except in the JD-only fixture, where its JD differs.

| Fixture | Requisitions 1/2 | Titles 1/2 | Locations 1/2 | Current visible groups for rows 1/2 |
|---|---|---|---|---:|
| requisition | R1/R1 | Engineer/Engineer | Israel/Israel | 1 |
| distinct | R1/R2 | Engineer/Engineer | Israel/Israel | 1, overmerged |
| title | R1/R1 | Engineer/Updated Engineer | Israel/Israel | 2, duplicate |
| location | R1/R1 | Engineer/Engineer | Tel Aviv, Israel/Haifa, Israel | 2, duplicate |
| jd | absent/absent, shared JD | Engineer/Updated Engineer | Israel/Israel | 2, duplicate |
| role | R1/R1, shared role URL | Engineer/Updated Engineer | Israel/Israel | 1 |
| city | R1/R1 | Engineer/Engineer | Tel Aviv-Yafo/Herzliya | 0, geography rejection |

`representative` describes storage identity; `processed` retains accepted transport
rows. Current `VisibleGroups` applies `UiGroups` to stored rows. This models
`ui/lib/job-dedup.ts:groupDuplicateJobs`: ascending stable IDs, first compatible
group, and complete linkage across every member. `UiSameRole` requires equal
employers, compatible locations, and either equal canonical role keys or titles.
Role keys abstract recognized posting URLs, independently of requisition evidence.
Location compatibility covers equality and Israel country containment for this
finite input domain. Publication times are equal, so the lowest ID represents a
group. Date aggregation and other URL/location forms are outside this model.

Target visibility uses employer+requisition, with JD-only grouping when both
requisitions are absent. Known distinct requisitions override shared JD text.
`OneVisibleVacancy` checks group coverage and both directions of vacancy identity,
so it rejects both overmerged headcounts and duplicates across visible groups.

Receipts include fetched/matched source metrics in BOTH modes. Current metrics
map to `harvest.py`'s `source_fetch_counts` and `source_match_counts`, preserved by
`cloud_run.py:main` in `receipt.result`. All-filtered loss ALREADY satisfies I-a
through fetched>0, matched=0, even without an all-filtered warning. Zero totals for
an excluded source do not identify registered or excluded boards. Missing current
registered/eligible/requested/filtered/inserted fields are abstracted as -1;
target exclusions add warnings and registered/eligible counts. `inserted` counts
processed transport rows, independently of visible grouping.

Checks return success/unknown/dead once per visible vacancy per tick. Historical
conclusive evidence and closure survive unknown; latest/checkedAt track attempts.
Target alive requires a latest success within FreshFor=1 and the inclusive deadline
of 1 for rows 1/2. Current alive abstracts a consumer using historical positive
alone. Triage established ambiguous stored evidence, not a confirmed UI defect.
Dead abstracts conclusive removal after the checker's confirmation policy.

This proves bounded safety of a proposed design. It does not verify production
Python or UI execution. Concurrency, recurring refresh, retries, transactions,
cross-source harvest suppression, unknown employers, arbitrary JD equivalence,
and progress/fairness are outside scope. Intentional horizon-end states disable
deadlock checking.

## TLC results

Run: 2026-10-22, TLC 2.19, BellSoft Java 11.0.16.1 as reported by TLC.
One worker, fingerprint 0, seed 1. The target has no state constraints.
Logs retained locally at `/tmp/jrc-tlc-p0f1-final2`; rerun the command above to reproduce.

| Configuration / invariant | Result | Generated | Distinct | Depth |
|---|---|---:|---:|---:|
| Target / all four invariants | PASS | 81847 | 25056 | 14 |
| Current NoSilentSourceLoss / stale registry | violation | 22 | 8 | 2 |
| Current OneVisibleVacancy / distinct requisitions | violation | 85 | 67 | 6 |
| Current AliveImpliesFreshCheck / unknown after success | violation | 1280 | 1150 | 9 |
| Current LocationAcceptsCityOnly / city fixture | violation | 188 | 188 | 4 |
| Current NoSilentSourceLoss / GeoWitness | PASS | 310 | 166 | 10 |
| Current OneVisibleVacancy / RequisitionWitness | PASS | 5484 | 1739 | 14 |
| Current OneVisibleVacancy / RoleWitness | PASS | 5484 | 1739 | 14 |
| Current OneVisibleVacancy / TitleWitness | violation | 85 | 67 | 6 |
| Current OneVisibleVacancy / LocationWitness | violation | 85 | 67 | 6 |
| Current OneVisibleVacancy / JdWitness | violation | 85 | 67 | 6 |

Each violation stops its own run; passing rows exhaust their bounded state spaces.
Constraints select immutable fixtures, never changing pipeline state. Generated
counts include initial states outside constraints. GeoWitness retains the reviewed
166 distinct states and depth 10; 310 generated replaces 298 because the expanded
fixture domain generates 21 initial candidates instead of 9.

## Trimmed current-code traces

```text
NoSilentSourceLoss: Init(stale,jd) → Registry, depth 2.
  Lever age=2 > MaxAge=1, eligible={comeet,workable};
  receipt.lever.registered=eligible=-1, warnings={}. Exclusion is silent.

GeoWitness: Init(fresh,city) → Registry → Fetch({1,2}) → Filter.
  geo=matched={}, comeet.fetched=2, comeet.matched=0, warnings={}.
  I-a PASSES. I-d still rejects this state for losing Israeli cities.

OneVisibleVacancy: Init(disabled,distinct) → Registry → Fetch({1,2}) → Filter
  → Upsert(1) → Upsert(2), depth 6. Stored rows={1,2}.
  Derived VisibleGroups={{1,2}} despite requisitions R1/R2: overmerge.
  TitleWitness repeats these steps with R1/R1 and different titles:
  Derived VisibleGroups={{1},{2}}: duplicate vacancy groups.
  LocationWitness repeats with Tel Aviv, Israel/Haifa, Israel and R1/R1:
  Derived VisibleGroups={{1},{2}}, even when role keys match.
  JdWitness repeats with absent requisitions, shared JD, different titles:
  Derived VisibleGroups={{1},{2}}. Equal-title/location R1/R1 and shared-URL
  title drift instead PASS, each with VisibleGroups={{1,2}}.

AliveImpliesFreshCheck: Init(disabled,jd) → Registry → Fetch({3}) → Filter
  → Upsert(3) → Finish → Check(3,success) → Tick → Check(3,unknown), depth 9.
  now=checkedAt[3]=1, latest[3]=unknown, historical[3]=TRUE, closed={}.
  The historical-positive projection still displays row 3 alive.

LocationAcceptsCityOnly: Init(disabled,city) → Registry → Fetch({1,2})
  → Filter, depth 4. Tel Aviv-Yafo and Herzliya yield geo=matched={}.
```

## Invariant → code → required fix tests

Baseline: `a1caf93efec5e823a899315db1116269e847f41b`. Evidence includes coach triage
`2026-10-21-jrc-triage/COMEET-CHECK.md` and `SUMMARY.md`, duplicate-identity and
stale-liveness sections. Code and existing `ui/tests/job-dedup.test.ts` were read.
Names below are requirements for later fix PRs, not tests added or claimed failing here.
The all-filtered receipt case is an existing-behavior regression control.

| Invariant | Code sites | Required test names |
|---|---|---|
| NoSilentSourceLoss | `scraper/source_registry.py:load_registry`, `RegistryReport.source_queries`; `scraper/harvest.py:load_registry_source_queries`; `scraper/cloud_run.py:main` | `scraper/test_cloud_run.py::test_receipt_surfaces_stale_and_disabled_boards`; `scraper/test_cloud_run.py::test_receipt_preserves_all_filtered_source_metrics` |
| OneVisibleVacancy, visible groups | `ui/lib/job-dedup.ts:sameRole`, `groupDuplicateJobs`; `ui/lib/repost-locations.ts:compatibleFacts` | `ui/tests/job-dedup.test.ts::same_requisition_title_drift_has_one_group`; `ui/tests/job-dedup.test.ts::same_requisition_location_variants_have_one_group`; `ui/tests/job-dedup.test.ts::distinct_requisitions_with_same_title_location_and_jd_stay_separate`; `ui/tests/job-dedup.test.ts::jd_only_title_variants_have_one_group` |
| OneVisibleVacancy, transport evidence | `scraper/harvest.py:dedupe_postings`, `_posting_secondary_key`; `scraper/database.py:_posting_values`, `POSTING_UPSERT` | `scraper/test_harvest.py::test_same_source_reposts_retain_requisition_evidence`; `scraper/test_harvest.py::test_distinct_requisitions_with_shared_jd_are_retained`; `scraper/test_database.py::test_distinct_source_ids_are_retained_for_vacancy_grouping` |
| AliveImpliesFreshCheck | `scraper/ats_liveness.py:reliability_update`; future freshness/deadline display projection | `scraper/test_ats_liveness.py::test_unknown_after_success_preserves_history_without_fresh_alive`; `scraper/test_ats_liveness.py::test_expired_check_is_not_displayed_alive`; `scraper/test_ats_liveness.py::test_past_deadline_is_not_displayed_alive` |
| LocationAcceptsCityOnly | `scraper/harvest.py:_location_matches`, `_source_posting_matches` | `scraper/test_harvest.py::test_city_only_israel_location_passes_israel_search`; `scraper/test_harvest.py::test_unrelated_country_fails_israel_search` |

Verification: `bash -n` and `git diff --check` pass. Temporary mutations that omit
current fetched metrics or treat stored rows as visible groups both fail the
runner. An in-memory probe calls the real `groupDuplicateJobs` with the six
non-city fixture pairs and obtains 1/1/2/2/2/1 groups, matching this model.
The first probe could not load the absent `tsx` dependency; the successful probe
uses Node 22's built-in TypeScript support with a local extension resolver.
No dependencies or application sources changed. This is function execution,
not browser or production verification. Independent review remains lead-owned.

Local CodeRabbit reported two major findings, both rejected against the artifact:
witnesses are already before the module footer and TLC resolves all six; I-b
already uses `VisibleGroups`, with the R1/R1 control passing. Grouping current
rows by `SameVacancy` would erase the demonstrated R1/R2 overmerge.
