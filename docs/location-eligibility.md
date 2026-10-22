# Location eligibility after scoring

The local scorer adds `eligibility` (`eligible`, `blocked`, `unknown`) and a quoted
`eligibility_reason` after validating professional fit. The model prompt, skill
score and recommendation stay unchanged. Citizenship is not location permission.
Scorer version 1.3 identifies the precision-first gate.

An eligible decision needs both explicit Israel/central-Israel location or remote
permission from Israel/worldwide, and no geographic restriction the parser cannot
positively resolve as allowing Israel. Supported negations are resolved before
restrictions. Every remaining restriction span vetoes a pass and is quoted in the
unknown reason, even when the location field says Israel or remote worldwide.
Unrecognized residency, citizenship, work authorization, time-zone, English and
Hebrew restriction wording stays unknown. Ordinary skill requirements such as
“Python and SQL required” are not geographic restrictions.

A block needs explicit evidence: a closed foreign-only applicant scope, mandatory
foreign residence/relocation, an explicit Israel exclusion, or a required
incompatible on-site/hybrid office. A location field or foreign remote scope alone
is not enough to block. `Remote (United States)`, a client location, optional
relocation, and ambiguous mixed office/remote options stay unknown. An explicit
foreign residency requirement blocks even when the location says Tel Aviv;
worldwide marketing wording does not cancel a mandatory US residence requirement.

Place knowledge comes from `scraper/geography.py`, shared with ingestion. Scope
parsing reads adjacent place alternatives, not every city in a sentence. Country
identifiers, configured city aliases and English/Hebrew regions are shared there;
unknown places stay unresolved. ISO country codes need uppercase in geographic
scopes, except conventional US/UK/EU abbreviations. IL means Israel in that scope;
this does not infer an Israeli alternative from an arbitrary address. Holon,
Rishon/Rishon LeZion and their Hebrew aliases join the existing central cities.
London, Austin and Toronto use the same shared city table as other ingestion
consumers. Inclusive lists can name Israel first or last. Excluding another
country from worldwide remote does not exclude Israel.

The central-region bar is a named-place rule, not a radius: the profile must
mention central/center/centre, Gush Dan or מרכז in its location or allowed
geographies, without a whole-country Israel/ישראל geography. Required offices in
Sasa, Galilee, Haifa, Jerusalem, Be'er Sheva, Yokneam and configured northern or
southern regions block for that profile. `Haifa, Israel` names one noncentral
office; Israel is a country qualifier, not a separate office option. A bare
noncentral location without an office requirement stays unknown. Israeli
alternatives associated with the same requirement can allow the role; unrelated
customer geography cannot become an office requirement. An Israel-wide profile
accepts those Israeli offices. Tel Aviv residence alone does not activate the bar.

Both harvest and laptop scoring receive work mode, the remote flag and verified
extraction facts. Laptop persistence fingerprints those local inputs and locks
the posting and extraction again before writing, so a changed snapshot is stale.
These inputs and the candidate's local geography do not enter the model prompt.
Extraction quotes must match the JD when it is available. Verified location facts
can supply missing location evidence.

The fields live in the existing `posting_scores.score_payload` JSON. Apply
migrations 0037 and 0038 before running the updated scoring writer: 0037 extends
and validates the existing payload constraint; 0038 excludes blocked rows from
the SQL `recommended` filter before its limit. Neither adds a column or rewrites
historical scores. Previously scored rows without eligibility show location
unknown until rescored; this change does not schedule a backfill.

AssessmentSheet qualifies `apply` advice for blocked and unknown locations,
including previous archived assessments. Unknown rows remain reviewable under
`recommended`; blocked rows are excluded. `good` continues to measure skill fit.

The 21 public excerpts in `scraper/fixtures/eligibility-triage.json` now produce
5 blocked and 16 unknown outcomes with the synthetic central-Israel profile.
Fourteen former blocks move to unknown because they lack a mandatory requirement,
foreign-only wording or a concrete required office. No triage case becomes
eligible. `eligibility-adversarial.json` retains all previous 49 inputs; `sol-17`
now blocks explicit US residence despite a Tel Aviv location, and `cursor-18`
(`Remote US/Canada/UK`) stays unknown without explicit exclusivity.
`eligibility-review-r2.json` covers both round-2 reviews, including central-city
controls. Ambiguous mixed office/remote options and time-zone requirements stay
unknown even where a reviewer expected eligible. `eligibility-fresh-r2.json`
records 20 separately declared probes. Tests also exercise unresolved restriction
vetoes, negations, ambiguous alternatives, country qualifiers, technical uses of
hybrid, extraction provenance, and Israel-wide profile overrides.

`eligibility-holdout-r2.json` adds 20 probes written after implementation. Four
intended readings conservatively remain unknown: prefix-only residents of Ireland,
customer residency in London, a London office separated from the hybrid wording,
and an Israel-based remote phrase. Tests permit the intended result or unknown
for these cases; the independent receipt reports all four as exact mismatches.
