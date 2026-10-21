# Job Radar pipeline: bounded safety model

Status: P0 implementation, ready for lead-routed independent review. No production
code, database, service, credentials, or CI configuration changed.

## Run locally

```sh
./spec/tla/check.sh
# Optional: retain raw logs and the exact per-witness configurations in a NEW directory.
TLC_LOG_DIR=/tmp/jrc-tlc-evidence ./spec/tla/check.sh
```

Requires Java, `rg`, and `tlc` on PATH (here `/Users/etanheyman/.local/bin/tlc`);
`TLC` overrides the executable. The runner copies the model to a temporary directory and
removes only that directory. It runs the target configuration, then checks each
invariant independently under `JrcPipeline_current.cfg`, plus two focused witnesses.
Expected failures require BOTH TLC exit 12 and the exact requested invariant error;
an unexpected pass, different invariant, or parser/runtime error fails the runner.
The current cfg is a base: append `INVARIANT <name>` to run it manually.

## Scope and interpretation

The abstract pipeline is registry → eligible queries → fetch → geography/title
filter → source-ID upsert and vacancy grouping → liveness checks → displayed alive.
There are three boards (one per source), four postings, nine initial combinations
of registry and posting fixtures, and clock values 0..2. Registry age is either
MaxAge=1 (eligible boundary) or 2 (stale); one fixture disables Workable. Eligible
fetches can succeed or fail independently. Upserts run in every posting order.

Postings 1/2 are same-source, different external IDs. They share an employer and
either R1 or a JD-only group. Posting 3 has distinct R2, sharing the JD in the
requisition fixture. Posting 4 is London with a nonmatching title. City fixtures
use Tel Aviv-Yafo and Herzliya; country fixtures use Israel. Geography is evaluated
before title filtering, so the foreign negative control is independently checked.

`representative` groups visibility while `processed` retains every accepted
source row. Known distinct requisitions override shared JD text. JD-only grouping
requires both requisitions absent; mixed known/unknown identity stays separate
pending reconciliation. This conservative rule avoids ambiguous transitive groups.

Checks return success/unknown/dead, at most once per visible vacancy per tick.
`historical` retains the prior conclusive result; `latest`/`checkedAt` track the
latest attempt. Unknown preserves both historical evidence and closure state,
including a prior confirmed dead result. Target alive display derives from the
latest successful check within FreshFor=1 and an inclusive application deadline
(1 for postings 1/2). Current display derives from historical positive evidence.
`dead` abstracts a conclusive removal after the real checker's confirmation policy.

Receipts track registered/eligible/requested/parsed/filtered/inserted and warnings.
Target exclusions surface a warning or accurate counters. Current missing receipt
counters are -1: aggregate console logs are not per-source receipt evidence.
`inserted` counts retained transport rows, not visible groups, in this one-batch model.

This checks safety of the proposed design, not the Python implementation or UI.
The current alive projection models a consumer treating stored `alive` alone as
fresh; triage established ambiguous stored evidence, not a confirmed UI defect.
The bounded model excludes concurrency, recurring registry refresh, retries,
database transactions, cross-source company/title heuristics, unknown employers,
and arbitrary JD equivalence. It makes no progress/fairness claim. Deadlock checking
is disabled because horizon-end terminal states are intentional.

## Target design: all-pass receipt

Run: 2026-10-22 local machine date, TLC 2.19 / tla2tools 1.7.4, Java 17.0.19.
One worker, fingerprint 0, seed 1; no state constraints on the target.

```text
Model checking completed. No error has been found.
31893 states generated, 9894 distinct states found, 0 states left on queue.
The depth of the complete state graph search is 14.
```

All four named invariants passed. `OneVisibleVacancy` checks both directions of
group equivalence and representative validity, preserving distinct requisitions.
`AliveImpliesFreshCheck` also checks unknown preserves the preceding closure state.

## Current behavior: counterexamples (trimmed TLC traces)

Each row is a separate TLC execution, stopped at its expected violation. Counts
include generated states outside the fixed-fixture constraint; these are not full
state-space explorations. Constraints select only unchanging fixture variables.

| Requested invariant / witness | Generated | Distinct | Depth |
|---|---:|---:|---:|
| NoSilentSourceLoss / stale registry | 10 | 4 | 2 |
| NoSilentSourceLoss / GeoWitness | 20 | 12 | 4 |
| OneVisibleVacancy / same requisition | 73 | 67 | 6 |
| OneVisibleVacancy / JdWitness | 73 | 67 | 6 |
| AliveImpliesFreshCheck / unknown after success | 561 | 511 | 9 |
| LocationAcceptsCityOnly / city fixture | 84 | 84 | 4 |

```text
Error: Invariant NoSilentSourceLoss is violated.
1 Init: registryCase="stale", fixture="jd", receipt.lever.warnings={}
2 Registry: eligible={"comeet","workable"}; Lever age=2 > MaxAge=1;
  receipt.lever.eligible=-1, warnings={} (no surfaced exclusion).

Error: Invariant NoSilentSourceLoss is violated. [GeoWitness]
1 Init: registryCase="fresh", fixture="city"
2 Registry: eligible={"comeet","lever","workable"}
3 Fetch: fetched={1,2}; other fetches fail with warnings
4 Filter: geo={}, matched={}; receipt.comeet.warnings={}, parsed/filtered=-1.

Error: Invariant OneVisibleVacancy is violated.
1 Init: fixture="requisition", registryCase="disabled"
2 Registry: eligible={"comeet","lever"}
3 Fetch: fetched={1,2}
4 Filter: geo=matched={1,2}
5 Upsert(1): processed={1}, representative=<<1,0,0,0>>
6 Upsert(2): processed={1,2}, representative=<<1,2,0,0>>;
  two visible vacancies for Employer/R1. JdWitness repeats this with empty
  requisitions and the same normalized JD group (also depth 6).

Error: Invariant AliveImpliesFreshCheck is violated.
1 Init: fixture="jd", registryCase="disabled", now=0
2 Registry; 3 Fetch: fetched={3}; 4 Filter: matched={3}
5 Upsert(3); 6 Finish: phase="live"
7 Check(3,success): checkedAt[3]=0, historical[3]=TRUE
8 Tick: now=1
9 Check(3,unknown): checkedAt[3]=1, latest[3]="unknown",
  historical[3]=TRUE, closed={}; displayed alive still includes 3.

Error: Invariant LocationAcceptsCityOnly is violated.
1 Init: fixture="city", registryCase="disabled"
2 Registry: eligible={"comeet","lever"}
3 Fetch: fetched={1,2}
4 Filter: geo={}, matched={}; Tel Aviv-Yafo and Herzliya both rejected.
```

## Invariant → code site → required fix tests

Source baseline: `a1caf93efec5e823a899315db1116269e847f41b`. Evidence:
coach triage `2026-10-21-jrc-triage/COMEET-CHECK.md` and `SUMMARY.md`,
section “JRC issues — merged and ranked”, items 1 and 4. Code sites below were
read in this checkout. These test names are requirements for subsequent fix PRs;
they are not tests added or claimed failing by this P0 change.

| Invariant | Code sites to fix | Required test names |
|---|---|---|
| NoSilentSourceLoss | `scraper/source_registry.py:load_registry`, `RegistryReport.source_queries`; `scraper/harvest.py:load_registry_source_queries`, `filter_source_postings`; `scraper/cloud_run.py:_base_receipt` | `scraper/test_cloud_run.py::test_receipt_surfaces_stale_and_disabled_boards`; `scraper/test_cloud_run.py::test_receipt_surfaces_all_filtered_source` |
| OneVisibleVacancy | `scraper/harvest.py:dedupe_postings`, `_posting_secondary_key`; `scraper/database.py:_posting_values`, `POSTING_UPSERT` | `scraper/test_harvest.py::test_same_employer_requisition_has_one_visible_vacancy`; `scraper/test_harvest.py::test_jd_only_duplicates_have_one_visible_vacancy`; `scraper/test_harvest.py::test_distinct_requisitions_with_shared_jd_remain_visible` |
| AliveImpliesFreshCheck | `scraper/ats_liveness.py:reliability_update`, plus the future freshness/deadline display projection | `scraper/test_ats_liveness.py::test_unknown_after_success_preserves_history_without_fresh_alive`; `scraper/test_ats_liveness.py::test_expired_check_is_not_displayed_alive`; `scraper/test_ats_liveness.py::test_past_deadline_is_not_displayed_alive` |
| LocationAcceptsCityOnly | `scraper/harvest.py:_location_matches`, `_source_posting_matches` | `scraper/test_harvest.py::test_city_only_israel_location_passes_israel_search`; `scraper/test_harvest.py::test_unrelated_country_fails_israel_search` |

Runner verification: `bash -n` passed; temporary fake TLC executables returning
unexpected success, the wrong invariant, or a parse error were each rejected.
Local CodeRabbit check: completed with one minor finding (portable TLC lookup),
fixed; the full TLC runner passed again. Independent review remains lead-owned.
