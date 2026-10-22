# Location eligibility after scoring

The local scorer adds `eligibility` (`eligible`, `blocked`, `unknown`) and a quoted
`eligibility_reason` after validating professional fit. The model prompt, skill
score and recommendation stay unchanged. Citizenship is not location evidence.

Israel and recognized Israeli cities pass. A profile limited to central Israel
blocks an explicitly on-site/hybrid noncentral office; an Israel-wide profile does
not impose that central-region limit. Remote roles need explicit Israel or
worldwide scope. A generic US listing, missing evidence and conflicting evidence
stay unknown. Extraction quotes must match the JD when it is available.

Explicit Israel exclusions, Hebrew US-residents-only requirements, foreign-city
residency/relocation demands and concrete incompatible on-site offices block even
when the location field says Israel. Inclusive remote lists may name Israel first
or last. An exception excluding another country does not exclude Israel.

The central-region bar is a named-place rule, not a radius: the profile must
mention central/center/centre, Gush Dan or מרכז in its location or allowed
geographies, without a whole-country Israel/ישראל geography. It blocks required
offices in Sasa, Galilee, Haifa, Jerusalem, Be'er Sheva, Yokneam, northern/southern
regions and their configured Hebrew spellings, whether named in the location or
role-specific JD clause. It does not infer a central limit merely from Tel Aviv
residence. The regression profile allows `Central Israel` and `Remote`; the
Israel-wide counter-tests allow `Israel` and accept those Israeli offices.

Both harvest and laptop scoring receive work mode, the remote flag and verified
extraction facts. Laptop persistence fingerprints those local inputs and locks
the posting and extraction again before writing, so a changed snapshot is stale.
These inputs and the candidate's local geography do not enter the model prompt.

The fields live in the existing `posting_scores.score_payload` JSON. Apply
migrations 0037 and 0038 before running the updated scoring writer: 0037 extends
and validates the existing payload constraint; 0038 excludes blocked rows from
the SQL `recommended` filter before its limit. Neither adds a column or rewrites
historical scores. Previously scored rows without eligibility show location
unknown until rescored; this change does not schedule a backfill.

AssessmentSheet qualifies `apply` advice for blocked and unknown locations,
including previous archived assessments. Unknown rows remain reviewable under
`recommended`; blocked rows are excluded. `good` continues to measure skill fit.

The 21 public geographic excerpts in `scraper/fixtures/eligibility-triage.json`
produce 19 blocked and 2 unknown outcomes with the synthetic central-Israel
profile. Tests also cover Israeli cities, worldwide remote, citizenship,
conflicts, extraction fallback and unrelated customer geography.
`eligibility-adversarial.json` adds the Sol and Cursor review strings. Two Sol
expectations are strengthened by the fix brief: an Israel location plus either
Hebrew US-only residence or an explicit Israel exclusion is blocked, not unknown.
