import patterns from "./experience-patterns.json";

/** Workable's Markdown export is ingestion data, not a human-facing job page. */
export function postingUrl(value: string): string {
  const url = new URL(value);
  if (url.hostname === "apply.workable.com") {
    const match = url.pathname.match(/^\/([^/]+)\/jobs\/view\/([a-z0-9]+)\.md$/i);
    if (match) url.pathname = `/${match[1]}/j/${match[2]}/`;
  }
  return url.toString();
}

// Mirrored in SQL public.board_level_rank (0025); update its parity fixtures when changing these regexes.
export function titleSeniority(title: string): string | null {
  if (/\b(intern|internship)\b/i.test(title)) return "Intern";
  if (/\b(junior|jr\.?|graduate|entry[- ]level)\b/i.test(title)) return "Junior";
  if (/\b(principal|staff)\b/i.test(title)) return "Staff / Principal";
  if (/\b(lead|manager|head|director)\b/i.test(title)) return "Lead / Manager";
  if (/\b(senior|sr\.?)\b/i.test(title)) return "Senior";
  if (/\b(mid[- ]level|intermediate)\b/i.test(title)) return "Mid-level";
  return null;
}

/** One-for-one masking preserves source offsets while sharing SQL's clause boundaries. */
function normalizeExperienceText(description: string): string {
  let text = description;
  for (const char of patterns.normalization.space) text = text.replaceAll(char, " ");
  for (const char of patterns.normalization.newline) text = text.replaceAll(char, "\n");
  for (const pattern of patterns.normalization.mask) {
    text = text.replace(new RegExp(pattern, "gmi"), match => " ".repeat(match.length));
  }
  return text;
}

/** Quote a mandatory minimum; unresolved tenure blocks specialist fallback. */
export function experiencePhrase(description: string | null): string | null {
  if (!description) return null;
  const normalized = normalizeExperienceText(description);
  const number = patterns.number;
  const phrase = new RegExp(patterns.englishTail.map(tail => patterns.englishLead + tail).concat(patterns.hebrew).join("|"), "gi");
  const test = (pattern: string, text: string) => new RegExp(pattern, "i").test(text);
  const amount = (token: string) => /^[0-9]+$/.test(token) ? Number(token) : patterns.words.indexOf(token.toLowerCase());
  if (test(patterns.fractionalTenure, normalized) || new RegExp(patterns.numberedTenure, "mi").test(normalized)) return null;
  let selected: { minimum: number; quote: string; rank: number } | null = null;
  let disagreement = false;
  for (const clauseMatch of normalized.matchAll(/[^.!?;\n]+/g)) {
    let clause = clauseMatch[0];
    // Only a higher numeric preference is exempt; masking keeps source offsets.
    for (const preference of clause.matchAll(new RegExp(patterns.preference, "gi"))) {
      const preceding = [...clause.slice(0, preference.index).matchAll(new RegExp(patterns.extraNumber, "gi"))].at(-1)?.[0];
      const preferred = preference[0].match(new RegExp(patterns.extraNumber, "i"))?.[0];
      if (preceding && preferred && amount(preferred) >= amount(preceding)) {
        clause = clause.slice(0, preference.index) + " ".repeat(preference[0].length) + clause.slice(preference.index + preference[0].length);
      }
    }
    const domainPreference = new RegExp(patterns.domainPreference, "i").exec(clause);
    if (domainPreference && !test(patterns.extraNumber, domainPreference[0]) && !test(patterns.tenure, domainPreference[0])) {
      clause = clause.slice(0, domainPreference.index) + " ".repeat(domainPreference[0].length);
    }
    if (!test(patterns.numericTenure, clause)) continue;
    const matches = [...clause.matchAll(phrase)];
    const contextEnd = matches[0]?.index ?? clause.length;
    let section: "applicant" | "optional" | "other" = "other";
    for (const heading of normalized.slice(0, clauseMatch.index + contextEnd).matchAll(new RegExp(patterns.headings, "gmi"))) {
      const text = (heading[1] ?? heading[2] ?? heading[3]).replace(/[:#*]+$/, "").replace(/^[^A-Za-zא-ת]+/, "").trim();
      if (!/[.!?;]/.test(text) && test(patterns.optionalScope, text) && !test(patterns.headingTenure.replaceAll("{number}", number), text)) section = "optional";
      else if (test(patterns.requiredHeading, text)) section = "applicant";
      else if (test(patterns.otherHeading, text)) section = "other";
    }
    if (test(patterns.inlineRequiredHeading, clause)) section = "applicant";
    if (section === "optional" || test(patterns.company, clause.slice(Math.max(0, contextEnd - 180), contextEnd))) continue;
    if (matches.length > 0 && test(patterns.company, clause.slice(matches[0].index + matches[0][0].length))) continue;
    const context = clause.slice(0, contextEnd);
    if (test(patterns.employerVerb, context) && !test(patterns.applicantVerb, context)) continue;
    if (test(patterns.precedingNumber, context)) return null;
    const residue = matches.length === 1 ? clause.replace(matches[0][0], "") : clause;
    if ((matches.length > 0 && test(patterns.complexity, clause.slice(matches[0].index + matches[0][0].length)))
      || test(patterns.optionalScope, clause)) return null;
    if (section !== "applicant" && !test(patterns.requiredContext, clause) && !test(patterns.domainContext, clause)) continue;
    if (test(patterns.reject, residue) || test(patterns.alternativeNumber, residue)) return null;
    if (matches.length !== 1 || test(patterns.tenure, residue)) return null;
    const match = matches[0];
    if (test(patterns.complexity, match[0])
      || test(patterns.extraNumber, match[0].replace(new RegExp(patterns.quantity, "i"), ""))) return null;
    const amounts = [...match[0].matchAll(new RegExp(patterns.extraNumber, "gi"))].map(token => amount(token[0]));
    const minimum = amounts[0];
    if (minimum === undefined || (amounts.length > 1 && amounts[1] < minimum)) return null;
    const withoutLead = match[0].replace(/^minimum(?:[ \t]+of)?[ \t]+/i, "");
    const quoteStart = clauseMatch.index + match.index + match[0].length - withoutLead.length;
    const quote = description.slice(quoteStart, quoteStart + withoutLead.length);
    const rank = (section === "applicant" ? 2 : 0) + Number(test(patterns.role, clause));
    if (!selected || rank > selected.rank) {
      selected = { minimum, quote, rank };
      disagreement = false;
    } else if (rank === selected.rank && minimum !== selected.minimum) disagreement = true;
  }
  return disagreement ? null : selected?.quote ?? null;
}

/** Display explicit mentions only; these are not proficiency or must-have claims. */
export function technologyMentions(description: string | null): string[] {
  if (!description) return [];
  const technologies: [string, RegExp][] = [
    ["React Native", /\breact\s+native\b/i], ["React", /\breact(?:\.?js)?\b(?!\s+native\b)/i], ["TypeScript", /\btypescript\b/i],
    ["JavaScript", /\bjavascript\b/i], ["Next.js", /\bnext\.?js\b/i],
    ["Node.js", /\bnode\.?js\b/i], ["Python", /\bpython\b/i],
    ["PostgreSQL", /\bpostgres(?:ql)?\b/i], ["Docker", /\bdocker\b/i],
    ["Kubernetes", /\b(?:kubernetes|k8s)\b/i], ["AWS", /\b(?:aws|amazon web services)\b/i],
    ["Azure", /\b(?:azure|microsoft cloud)\b/i], ["GCP", /\b(?:gcp|google cloud(?: platform)?)\b/i],
    ["Go", /\bgolang\b|\b(?:experience|proficiency|expertise|development)\s+(?:with|in|using)\s+go\b|\b(?:tech(?:nology)?\s+stack|programming\s+languages?|languages?)\s*:?[^.\n]{0,80}\bgo\b|(?:^|[,;/|])\s*go\s*(?=\s*(?:[,);/|]|$))/im], ["Java", /\bjava\b/i],
    ["Vue", /\bvue(?:\.js|js)?\b/i], ["Angular", /\bangular\b/i],
    ["C#", /\bc#(?=\W|$)/i], ["C++", /\bc\+\+(?=\W|$)/i],
    ["MongoDB", /\bmongodb\b/i], ["Redis", /\bredis\b/i], ["Kafka", /\bkafka\b/i],
    ["Elasticsearch", /\belasticsearch\b/i], ["Terraform", /\bterraform\b/i],
    ["GitHub Actions", /\bgithub actions\b/i], ["Linux", /\blinux\b/i],
    [".NET", /(?:^|\W)(?:\.net|dotnet)\b/i], ["SQL Server", /\bsql server\b/i],
    ["SQL", /\bsql\b(?!\s+server\b)/i], ["PHP", /\bphp\b/i], ["Ruby", /\bruby\b/i],
    ["Rails", /\brails\b/i], ["Kotlin", /\bkotlin\b/i], ["Rust", /\brust\b/i],
    ["Scala", /\bscala\b/i], ["Bash", /\bbash\b/i], ["FastAPI", /\bfastapi\b/i],
    ["Django", /\bdjango\b/i], ["Spring", /\bspring boot\b|\bspring framework\b|\bjava(?:\s+and|[,/])?\s+spring\b|\bspring\b(?=[,)]\s+(?:and\s+)?related technologies)/i],
    ["Express", /\bexpress(?:\.js|js)\b|\bexpress framework\b|\bnode\.?js\s*\/\s*express\b|\busing express\b/i], ["GraphQL", /\bgraphql\b/i],
  ];
  return technologies.filter(([, pattern]) => pattern.test(description)).map(([name]) => name);
}
