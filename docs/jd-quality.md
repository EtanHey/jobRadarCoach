# JD quality gate

`scraper.jd_quality.jd_quality_rule` detects structural defects in stored text.
No match means unknown quality; it does not certify a usable JD.

The existing relevance gate stores one of these reasons:

- `jd-quality-missing-body`: null or whitespace-only body.
- `jd-quality-unfilled-template`: a hiring sentence still contains `[Job Title]`
  and the experience field still contains `[number] years`.
- `jd-quality-mixed-role`: a role-selection question plus independent role
  introductions with different supported role heads.
- `jd-quality-listing-only`: an openings heading and multiple job links, with
  no other body text.
- `jd-quality-external-summary`: an explicit external-JD pointer, with only
  recognized hiring/invitation sentences and optional document instructions.

Unknown structures, missing skill lists, short prose, and links appended to a
substantive JD do not alone trigger a rejection. Role-head recognition is closed
to engineer/developer/manager/designer; unsupported or same-head roles abstain.

The gate runs at ingestion and before extraction/scoring selection. It also
rechecks previously scored rows and missing bodies in bounded backlog passes.
Flagged rows move to **Not scored**, which suppresses their current score and
recommendation; existing assessments remain available as **Previous** history.
Pursued statuses and explicit **Score anyway** overrides retain their existing
protection. Replacing the body resets the gate and allows recovery on refresh.
The pure scoring helpers and the existing SQL pursuit/return and score-refresh
policies are unchanged; this slice gates the automatic selection path.

Offline replay (no DB, provider, or network access):

```sh
python -m scripts.jd_quality_dryrun snapshot.jsonl docs.local/jdq-snapshot.json --base 39a8617
```

This change performs no production backfill or service installation. Deploying
the cloud scraper and analysis wheel, then refreshing the gate, is a lead-owned
rollout; tests and frozen-snapshot replay are not live-service evidence.
