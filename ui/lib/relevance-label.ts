const labels: Record<string, string> = {
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
