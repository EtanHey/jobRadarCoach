# Location eligibility after scoring

The local scorer adds `eligibility` (`eligible`, `blocked`, `unknown`) and a quoted
`eligibility_reason` after validating professional fit. The model prompt, skill
score and recommendation stay unchanged. Citizenship is not location permission.
Scorer version 1.3 identifies the precision-first gate.

A positively resolved Israeli posting location supplies permission. A description
clause can reopen that decision only with a positive non-own place signal: a
foreign place or another Israeli place, a non-own workplace/proximity slot, a
foreign nationality credential, or a time zone outside Israel/IST. Capitalized
workplace/proximity names need not belong to the gazetteer. Own-place names and
ordinary skill, policy, benefits and technical prose without such signals are
satisfied, including Israeli work authorization. The central-Israel commute
scope below is unchanged.

Missing, mixed, foreign and unparsed posting locations retain the precision-first
restriction parser: unresolved residence, applicant, credential and time-zone
frames still veto permission. Bounded policy and language-skill phrases are
removed without discarding independent requirements. Explicit Israel exclusions
always take priority. A foreign citizenship is not itself proof of residence.

A block needs explicit evidence: a closed foreign-only applicant or role work
scope, mandatory foreign residence/relocation, an explicit Israel exclusion, or a
required incompatible office. Complete remote location annotations (`Remote - US`,
`US Remote`, `Remote (United States)`) block without “only”. EMEA includes the
Middle East, so `Remote - EMEA` and `Remote, EMEA` remain unknown.
Role-specific bounded remote work, corroborated role base, fully enumerated US
hub-or-US-remote alternatives, and a labeled country-qualified mode list also
close the scope. Choosing onsite/hybrid/remote based on client requirements does
not change an explicitly stated country. Israel/worldwide alternatives, unknown
places and conditional country approval prevent these closed-scope blocks.
Bare foreign countries, client locations, optional relocation and authorization
alone remain unknown.

An Israeli location field takes precedence over a description's foreign-only
restriction: the result is unknown, quoting the restriction, so another office's
requirements cannot hide an Israeli posting. Missing, unparsed and conflicting
location fields use the same rule. Bare `Remote` is neutral and can still be
resolved by an explicit description restriction. Explicit exclusions of Israel
or Israelis, including excluded-country lists, remain blocked. The central-Israel
commute rule below also remains blocked. Parenthetical inclusions (`including`,
`incl.`, `such as`, `e.g.`) continue the region scope; Europe including Israel
cannot establish a foreign-only scope.

Prefix “only residents of” is mandatory residency. Concrete weekly attendance
(`3 days/week` or `three days each week in our London office`) and explicit
required office work use the same central/foreign office policy as hybrid work.
Unparsed attendance/office requirements veto eligibility. Office boilerplate for
some/other roles, another team or customers cannot establish this role's required
office. A contrast introducing a requirement (“remote, but candidates must be
based in US”) preserves it; a later exception offering Israel remains unresolved.

Place knowledge comes from `scraper/geography.py`, shared with ingestion. Scope
parsing reads adjacent place alternatives, not every city in a sentence. Country
identifiers, Hebrew names for all 249 ISO countries and territories (Unicode
CLDR 48.0.0), configured city aliases and English/Hebrew regions are shared there;
unknown places stay unresolved. ISO country codes need uppercase in geographic
scopes, except conventional US/UK/EU abbreviations. IL means Israel in that scope;
this does not infer an Israeli alternative from an arbitrary address. Holon,
Rishon/Rishon LeZion and their Hebrew aliases join the existing central cities.
London, Austin and Toronto use the same shared city table as other ingestion
consumers. Inclusive lists can name Israel first or last, including Hebrew או and
attached
ו alternatives with their own ב/ל/מ prefixes. Mixed Hebrew conjunctions remain
unknown when simultaneous residence cannot be ruled out. Every place slot must
be consumed: דרום אמריקה cannot resolve as the Israeli region דרום. An unparsed
remainder or unknown alternative prevents a block. Recognized foreign nationalities supply positive credential evidence for Israeli
postings; arbitrary adjectives alone do not. Unresolved applicant/credential
frames still veto eligibility for postings without a positively Israeli location.
Israeli demonyms can resolve an applicant slot, but citizenship alone never grants
location permission. Language-skill frames (speak/fluent/native/proficiency/language
and לדבר/דוברי/שפה/ברמת שפת אם) remain separate from nationality restrictions.
Excluding another country from worldwide remote does not exclude Israel.

Compatible Israeli ATS city/district/country qualifiers are normalized by the
shared geography module before parsing (for example, “Tel Aviv-Yafo, Tel Aviv
District, Israel” and “Raanana, Center District, Israel”). Complete “2 Locations,
Israel” fields are country-scoped. Unknown cities, conflicting foreign places
and noncentral office evidence are not discarded by normalization.

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

AssessmentSheet qualifies blocked `apply` advice and shows “location unclear”
with the quote for `unknown` reasons beginning `unresolved location restriction:`.
An `unknown` reason beginning `Israel/remote-from-Israel scope is unconfirmed:`
shows plain apply advice. The enum remains `eligible|blocked|unknown`; these
prefixes are the presentation contract for current and archived assessments.
Unrecognized reasons and legacy missing eligibility retain a conservative warning.
Both unknown kinds remain reviewable under `recommended`, like eligible rows;
blocked rows are excluded. `good` continues to measure skill fit.

The 21 public excerpts in `scraper/fixtures/eligibility-triage.json` produce
16 blocked and five unknown outcomes with the synthetic central-Israel profile.
Of the 14 rows discussed in round 3, 11 have closed foreign work scopes and three
remain ambiguous: Affirm's unnamed country of employment, a bare New York city
label, and agency/client geography. No triage case becomes eligible.
`eligibility-adversarial.json` retains all previous 49 inputs; the foreign remote
field expectations and `Remote US/Canada/UK` now follow the closed-scope policy.
The round-10 precedence ruling updates the older Israeli-location conflicts and
missing-location blocks to unknown; the receipt lists each changed expectation.
`eligibility-review-r3.json` adds both reviewers' probes and controls for optional
and negated attendance, other roles, unresolved places, Israel alternatives,
conditional country approval, authorization-only wording and nongeographic
requirements. The full snapshot replay also checks field alternatives spanning
semicolons, such as Israel alongside Remote - Europe.
`eligibility-review-r4.json` adds all supplemental reviewer probes, generic and
technical wording, Hebrew boundaries, policy/requirement mixtures, qualified ATS
locations and their conflicting/unknown-place controls.
`eligibility-review-r5.json` retains all round-5 probes plus policy-free controls,
contrast/semicolon variants, country-code applicant/authorization modifiers, Hebrew
prefixes/citizenship, and incidental-word/technical/policy controls.
`eligibility-review-r6.json` retains both round-6 reviewers' country, mixed-policy,
attendance and citizenship probes plus policy-free and technical controls.
The country/region matrix checks every Hebrew entry with all six attached
prefixes and common prefix combinations, including short names such as סין.

The holdout's Israeli-location conflicts now remain unknown under the same
precedence rule. Two intended readings remain
conservative unknowns: client residency in London and an Israel-based remote
phrase. Tests allow the intended result or unknown only for those two; replay
receipts count them as exact mismatches, not passes.

`eligibility-review-r7.json` retains both R7 reviewers' reported probes, Hebrew
alternatives, credentials, unseen demonyms and noun phrases, language controls,
and EEO-list/team-description controls followed by real restrictions. The round-10
658-row frozen snapshot has 49 blocked, 271 eligible and 338 unknown: three Figma
rows with unresolved composite location fields move from blocked to unknown.
Expim Haifa and Plasan Sasa retain their commute blocks. The Benin/building and Peru/Pro homographs remain
conservative unknowns, as does the unsupported London-office attendance probe.

P8C extends the same unresolved-slot method to role-limited/restricted wording,
place-based applicants without exclusivity, Hebrew intended-applicant wording,
and labeled eligible-country lists. These frames veto an unqualified pass when
the slot cannot resolve as Israeli. They do not infer a foreign country from a
demonym. Under the positive-Israeli-location rule, these explicit scope slots
also supply non-own place evidence, including unknown place names and country
codes; own-location and language-only controls remain satisfied.
Country-first `US residents only` uses the existing residence policy,
including the Israeli/unresolved-header downgrade. Bullet-separated ATS location
alternatives retain every field; recognized US city/state pairs use the shared
city and state tables. Unknown alternatives prevent a closed foreign scope.
Run `PYTHONPATH=. python scripts/eligibility_p8c_dryrun.py <snapshot.jsonl>` for
the frozen offline comparison against `origin/master`, including every decision
and reason change. Use `--baseline SHA` to pin the comparison. The only snapshot
decision changes are the three Figma bullet-field rows moving unknown to blocked.

When a posting's location resolves positively to Israel, own-workplace cleanup
still handles recognized addresses and work models. Residual prose without a
positive non-own signal no longer vetoes eligibility. An unfamiliar city with an
explicit Israeli country suffix retains unconfirmed commute scope. Existing
noncentral commute blocks remain in force.

Own-city matching uses shared geography aliases, including TLV/Tel-Aviv-Yafo,
Ramat-Gan and common transliteration variants. An Israel/Israeli office matches
a positive Israeli posting location. Numbered street addresses and recognized
local landmarks beside an explicit own-city mention do not add a workplace
restriction. Proximity destinations must resolve to that city, a recognized
local landmark, a transit noun phrase, or a street-type phrase; both ends of a
“between” address must resolve to the city, a local landmark, or a street-type
phrase. Building names require a recognized local landmark. Unrecognized names
such as Heathrow stay unresolved, including lowercase proximity destinations.
Address parsing preserves other cities and independent
attendance, residency or credential requirements. A named office with a numbered
address repeating the same city can resolve as that city's office. An office
environment or attendance in the office without a place slot is satisfied locally;
mixed workplace lists and unresolved cities remain unknown.

The bounded requirement to have legal authorization in the country where the
position is based is satisfied when that country resolves to Israel, including
the supported Hebrew equivalent. A separate foreign citizenship or non-own geographic requirement
remains unresolved. Composite Israeli/foreign fields cannot supply this assumption.

`python -m scripts.replay_own_office --plan PATH --snapshot PATH --out PATH`
replays the local P8E decision dump, frozen 658-row snapshot and retained probes
offline against a chosen baseline. The dump contains saved reason excerpts, so
its replay does not substitute for a full-JD production dry run.

### Recomputing stored unknown decisions

`python -m scripts.eligibility_backfill --recompute-unknown` previews only stored
`unknown` decisions for the current profile. Add `--apply` to write. Default
backfill mode still fills missing eligibility only. Recompute merges just
`eligibility` and `eligibility_reason`, preserves all other payload keys and score
columns, and skips identical decisions. SQL rechecks the current profile and
unknown value, preventing a stale plan from overwriting eligible/blocked scores.
The existing per-batch locks and profile-change guard apply to both modes.
