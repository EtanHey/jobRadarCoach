/** Workable's Markdown export is ingestion data, not a human-facing job page. */
export function postingUrl(value: string): string {
  const url = new URL(value);
  if (url.hostname === "apply.workable.com") {
    const match = url.pathname.match(/^\/([^/]+)\/jobs\/view\/([a-z0-9]+)\.md$/i);
    if (match) url.pathname = `/${match[1]}/j/${match[2]}/`;
  }
  return url.toString();
}

export function titleSeniority(title: string): string | null {
  if (/\b(intern|internship)\b/i.test(title)) return "Intern";
  if (/\b(junior|jr\.?|graduate|entry[- ]level)\b/i.test(title)) return "Junior";
  if (/\b(principal|staff)\b/i.test(title)) return "Staff / Principal";
  if (/\b(lead|manager|head|director)\b/i.test(title)) return "Lead / Manager";
  if (/\b(senior|sr\.?)\b/i.test(title)) return "Senior";
  if (/\b(mid[- ]level|intermediate)\b/i.test(title)) return "Mid-level";
  return null;
}

/** Quote only an explicit years-of-experience phrase, never infer it from level. */
export function experiencePhrase(description: string | null): string | null {
  if (!description) return null;
  const phrase = /\b\d{1,2}(?:\s*[-–]\s*\d{1,2})?\+?\s+years?\s+(?:of\s+)?(?:professional\s+|commercial\s+|relevant\s+|hands-on\s+)?experience\b/gi;
  for (const match of description.matchAll(phrase)) {
    const index = match.index;
    const boundary = Math.max(description.lastIndexOf(".", index - 1), description.lastIndexOf("!", index - 1), description.lastIndexOf("?", index - 1), description.lastIndexOf("\n", index - 1));
    const context = description.slice(boundary + 1, index).trim();
    const negative = /\b(?:no|not|without|ideally|preferably|bonus|wish|would|nice to have)\b/i.test(context);
    const required = /^(?:[-*•]\s*)?(?:(?:requirements?|qualifications?)\s*:\s*)?(?:at least|minimum(?: of)?|you (?:need|have|bring)|we require|requires?|required|must have|looking for|seeking)\s*(?:a|an)?\s*$/i.test(context);
    const headings = description.slice(0, index).matchAll(/^[ \t]*(?:#{1,6}[ \t]+([^\n]+)|((?:requirements?|qualifications?|what you bring|about(?: the)? company|about us|company|responsibilities|what you(?:'|’)ll do|the role|benefits))[ \t]*:?)[ \t]*$/gim);
    let applicantSection = false;
    for (const heading of headings) applicantSection = /^(?:requirements?|qualifications?|what you bring)$/i.test((heading[1] ?? heading[2]).replace(/[:#*]+$/, "").trim());
    const suffix = description.slice(index + match[0].length).split(/[.!?\n]/, 1)[0];
    const optional = /\b(?:not required|not necessary|optional|nice to have|bonus|preferred)\b/i.test(suffix);
    if (!negative && !optional && (required || (applicantSection && /^(?:[-*•]\s*)?$/.test(context)))) return match[0];
  }
  return null;
}

/** Display explicit mentions only; these are not proficiency or must-have claims. */
export function technologyMentions(description: string | null): string[] {
  if (!description) return [];
  const technologies: [string, RegExp][] = [
    ["React", /\breact(?:\.js|js)?\b/i], ["TypeScript", /\btypescript\b/i],
    ["JavaScript", /\bjavascript\b/i], ["Next.js", /\bnext\.?js\b/i],
    ["Node.js", /\bnode\.?js\b/i], ["Python", /\bpython\b/i],
    ["PostgreSQL", /\bpostgres(?:ql)?\b/i], ["Docker", /\bdocker\b/i],
    ["Kubernetes", /\bkubernetes\b/i], ["AWS", /\baws\b/i],
    ["Go", /\bgolang\b/i], ["Java", /\bjava\b/i],
    ["Vue", /\bvue(?:\.js|js)?\b/i], ["Angular", /\bangular\b/i],
    ["C#", /\bc#(?=\W|$)/i], ["C++", /\bc\+\+(?=\W|$)/i],
  ];
  return technologies.filter(([, pattern]) => pattern.test(description)).map(([name]) => name);
}
