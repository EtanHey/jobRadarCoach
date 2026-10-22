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

A block needs explicit evidence: a closed foreign-only applicant or role work
scope, mandatory foreign residence/relocation, an explicit Israel exclusion, or a
required incompatible office. Complete remote location annotations (`Remote - US`,
`US Remote`, `Remote (United States)`, `Remote, EMEA`) block without “only”. EMEA
has that policy only in complete location-field annotations, not arbitrary prose.
Role-specific bounded remote work, corroborated role base, fully enumerated US
hub-or-US-remote alternatives, and a labeled country-qualified mode list also
close the scope. Choosing onsite/hybrid/remote based on client requirements does
not change an explicitly stated country. Israel/worldwide alternatives, unknown
places and conditional country approval prevent these closed-scope blocks.
Bare foreign countries, client locations, optional relocation and authorization
alone remain unknown.

Prefix “only residents of” is mandatory residency. Concrete weekly attendance
(`3 days/week` or `three days each week in our London office`) and explicit
required office work use the same central/foreign office policy as hybrid work.
Unparsed attendance/office requirements veto eligibility. Office boilerplate for
some/other roles, another team or customers cannot establish this role's required
office. A contrast introducing a requirement (“remote, but candidates must be
based in US”) preserves it; a later exception offering Israel remains unresolved.

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

The 21 public excerpts in `scraper/fixtures/eligibility-triage.json` produce
16 blocked and five unknown outcomes with the synthetic central-Israel profile.
Of the 14 rows discussed in round 3, 11 have closed foreign work scopes and three
remain ambiguous: Affirm's unnamed country of employment, a bare New York city
label, and agency/client geography. No triage case becomes eligible.
`eligibility-adversarial.json` retains all previous 49 inputs; the foreign remote
field expectations and `Remote US/Canada/UK` now follow the closed-scope policy.
The round-2 review and fresh fixtures retain their precision-first expectations.
`eligibility-review-r3.json` adds both reviewers' probes and controls for optional
and negated attendance, other roles, unresolved places, Israel alternatives,
conditional country approval, authorization-only wording and nongeographic
requirements. The full snapshot replay also checks field alternatives spanning
semicolons, such as Israel alongside Remote - Europe.

The 20 independent holdout intentions stay unchanged. Prefix-only Ireland
residency and weekly London attendance now block. Two intended readings remain
conservative unknowns: client residency in London and an Israel-based remote
phrase. Tests allow the intended result or unknown only for those two; replay
receipts count them as exact mismatches, not passes.
