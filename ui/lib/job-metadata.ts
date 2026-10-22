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

/** Quote only an explicit years-of-experience phrase, never infer it from level. */
export function experiencePhrase(description: string | null): string | null {
  if (!description) return null;
  const number = patterns.number;
  const lead = `(?<![A-Za-z0-9_.])(?:(?:at least|minimum(?:[ \\t]+of)?|over|around)[ \\t]+)?${number}(?:[ \\t]*(?:[-–—]|to)[ \\t]*${number})?\\+?(?:[ \\t]+or more)?[ \\t]+(?:overall[ \\t]+)?years?\\b`;
  const phrase = new RegExp(patterns.englishTail.map(tail => lead + tail).concat(patterns.hebrew).join("|"), "gi");
  for (const match of description.matchAll(phrase)) {
    const index = match.index;
    const tokens = [...match[0].matchAll(new RegExp(`(?<![A-Za-z0-9_])${number}(?![A-Za-z0-9_])`, "gi"))];
    const wordNumber = tokens.some(token => /^[a-z]/i.test(token[0]));
    const amounts = tokens.map(amount => /^\d+$/.test(amount[0]) ? Number(amount[0]) : patterns.words.indexOf(amount[0].toLowerCase()));
    if (amounts.length > 1 && amounts[1] < amounts[0]) continue;
    const quoted = match[0]
      .replace(/^minimum(?:\s+of)?\s+/i, "")
      .replace(/\s+(?:with|and|in|who|that)$/i, "")
      .replace(/[.,;:]+$/, "");
    const boundary = Math.max(description.lastIndexOf(".", index - 1), description.lastIndexOf("!", index - 1), description.lastIndexOf("?", index - 1), description.lastIndexOf("\n", index - 1));
    const context = description.slice(boundary + 1, index).trim();
    const nearContext = context.slice(-180);
    const headings = description.slice(0, index).matchAll(new RegExp(patterns.headings, "gmi"));
    let section: "applicant" | "optional" | "other" = "other";
    for (const heading of headings) {
      const text = (heading[1] ?? heading[2] ?? heading[3]).replace(/[:#*]+$/, "").replace(/^[^A-Za-zא-ת]+/, "").trim();
      if (new RegExp(patterns.optionalHeading, "i").test(text)) section = "optional";
      else if (new RegExp(patterns.requiredHeading, "i").test(text)) section = "applicant";
      else if (new RegExp(patterns.otherHeading, "i").test(text)) section = "other";
    }
    const remainder = description.slice(index + match[0].length);
    const suffix = remainder.split(/[.!?\n;]/, 1)[0];
    const continuation = remainder.match(/^[^\n]*\n[ \t]+(?:or|או)(?=\s)[^\n]*/)?.[0] ?? "";
    const hebrew = /[א-ת]/.test(match[0]);
    if (new RegExp(patterns.reject, "i").test(`${nearContext} ${hebrew ? "" : match[0]} ${suffix} ${continuation}`)) continue;
    if (new RegExp(`(?<![A-Za-z0-9_])(?:${number})[ -]*$`, "i").test(nearContext)) continue;
    if (hebrew && !new RegExp(patterns.hebrewPrefix).test(nearContext)) continue;
    const optional = section === "optional" || /^\s*(?:[,;:–—-]\s*)?(?:is\s+)?(?:not required|not necessary|optional|nice to have|a plus|preferred)\b/i.test(suffix);
    const company = (/\b(?:has|have)\s*$/i.test(nearContext) && !/\b(?:you|must)\s+have\s*$/i.test(nearContext))
      || /\b(?:our|the|this)\s+(?:company|firm|business)\b[^.!?\n]{0,100}$/i.test(nearContext)
      || /\bour team\s+(?:has|combines|brings|boasts|offers)\b[^.!?\n]{0,80}$/i.test(nearContext)
      || /\bwe(?:'ve| have| bring| offer| boast)\b[^.!?\n]{0,80}$/i.test(nearContext)
      || /^\s*(?:serving (?:customers|clients)|in business|as a company)\b/i.test(suffix);
    const required = section === "applicant"
      || /\b(?:you (?:need|have|bring)|we (?:require|seek)|looking for|seeking|must(?: have)?|required|requirements?|minimum|all about you|your experience|what you bring|what you(?:'|’)ll need)\b/i.test(nearContext)
      || /^(?:at least|minimum)\b/i.test(match[0])
      || (hebrew && (/^(?:לפחות|ניסיון של לפחות|נסיון של לפחות)/.test(match[0]) || /נדרש|דרישות/.test(nearContext)))
      || (!wordNumber && /\b(?:software|engineering|developer|development|backend|frontend|full[- ]stack|devops|platform|infrastructure|data|hardware|verification|technical|programming|manufacturing|managing|product|sre)\b/i.test(`${match[0]} ${suffix.slice(0, 80)}`));
    if (!optional && !company && required) return quoted;
  }
  return null;
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
