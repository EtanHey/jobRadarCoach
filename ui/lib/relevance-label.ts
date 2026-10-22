// Keys are persisted relevance-gate rule slugs, not display text; keep unknown slugs visible for new rules.
const labels: Record<string, string> = {
  "jd-quality-missing-body": "JD quality: description is missing",
  "jd-quality-unfilled-template": "JD quality: unfilled role and experience placeholders",
  "jd-quality-mixed-role": "JD quality: description mixes separate roles",
  "jd-quality-listing-only": "JD quality: job links without a role description",
  "jd-quality-external-summary": "JD quality: full description is linked but not stored",
  "leadership-title-strict": "Leadership or staff-level role",
  "incompatible-stack-title": "Role requires a different primary stack",
  "years-minimum-7-strict": "Requires at least 7 years of experience",
  "mandatory-degree": "Requires a degree without an equivalent-experience option",
  "specialist-required": "Requires specialist experience",
  "pure-qa-title": "QA role", "support-title": "Support role",
  "technical-cofounder-title": "Technical co-founder or CTO role",
  "equity-only": "Equity-only compensation", "already-us-resident": "Must already live in the US",
};
export const relevanceLabel = (rule: string | null | undefined) => rule ? labels[rule] ?? rule : "Outside current preferences";
