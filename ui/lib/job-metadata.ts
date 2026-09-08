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
  const phrase = /\b(?:(?:at least|minimum(?:[ \t]+of)?|over|around)[ \t]+)?\d{1,2}(?:[ \t]*[-–—][ \t]*\d{1,2})?\+?[ \t]+years?\b(?:(?:[ \t]+of)?(?:[ \t]+(?:[a-z][\w+/-]*,?|\/)){0,7}?[ \t]+experience\b|[ \t]+(?:in|with)[ \t]+[a-z][\w+/-]*(?:[ \t]+[a-z][\w+/-]*){0,2}|(?:[ \t]+of)?[ \t]+(?:(?:professional|hands-on)[ \t]+){0,2}(?:(?:backend|frontend|full[- ]stack|software|platform|infrastructure|devops|data|hardware)[ \t]+)?(?:engineering|development)\b|[ \t]+(?:developing|building|working|operating|maintaining|leading|managing|designing)\b)/gi;
  for (const match of description.matchAll(phrase)) {
    const index = match.index;
    const quoted = match[0]
      .replace(/^minimum(?:\s+of)?\s+/i, "")
      .replace(/\s+(?:with|and|in|who|that)$/i, "")
      .replace(/[.,;:]+$/, "");
    const boundary = Math.max(description.lastIndexOf(".", index - 1), description.lastIndexOf("!", index - 1), description.lastIndexOf("?", index - 1), description.lastIndexOf("\n", index - 1));
    const context = description.slice(boundary + 1, index).trim();
    const nearContext = context.slice(-180);
    const headings = description.slice(0, index).matchAll(/^[ \t]*(?:#{1,6}[ \t]+([^\n]+)|([^\n]{1,48}))[ \t]*:?[ \t]*$/gm);
    let section: "applicant" | "optional" | "other" = "other";
    for (const heading of headings) {
      const text = (heading[1] ?? heading[2]).replace(/[:#*]+$/, "").trim();
      if (/^(?:preferred(?: qualifications?)?|nice to have|bonus|advantages?)$/i.test(text)) section = "optional";
      else if (/^(?:required|requirements?|qualifications?|minimum qualifications?|what (?:we(?:'|’)re looking for|you bring|you(?:'|’)ll need|it takes)|you bring|your experience|skills?\s*(?:&|and)\s*experience|who (?:you are|are you)|all about you|what we value)$/i.test(text)) section = "applicant";
      else if (/^(?:about(?: the)? company|about us|company|responsibilities|what you(?:'|’)ll do|the role|benefits|what we offer|compensation)$/i.test(text)) section = "other";
    }
    const suffix = description.slice(index + match[0].length).split(/[.!?\n]/, 1)[0];
    const negative = /\b(?:no|not|without|ideally|preferably|wish|would|nice to have)\b/i.test(nearContext);
    const optional = section === "optional" || /^\s*(?:[,;:–—-]\s*)?(?:is\s+)?(?:not required|not necessary|optional|nice to have|a plus|preferred)\b/i.test(suffix);
    const company = /\b(?:our|the|this)\s+(?:company|firm|business)\b[^.!?\n]{0,100}$/i.test(nearContext)
      || /\bour team\s+(?:has|combines|brings|boasts|offers)\b[^.!?\n]{0,80}$/i.test(nearContext)
      || /\bwe(?:'ve| have| bring| offer| boast)\b[^.!?\n]{0,80}$/i.test(nearContext)
      || /^\s*(?:serving (?:customers|clients)|in business|as a company)\b/i.test(suffix);
    const required = section === "applicant"
      || /\b(?:you (?:need|have|bring)|we (?:require|seek)|looking for|seeking|must(?: have)?|required|requirements?|minimum|all about you|your experience|what you bring|what you(?:'|’)ll need)\b/i.test(nearContext)
      || /^(?:at least|minimum)\b/i.test(match[0])
      || /\b(?:software|engineering|developer|development|backend|frontend|full[- ]stack|devops|platform|infrastructure|data|hardware|verification|technical|programming|manufacturing|managing|product|sre)\b/i.test(`${match[0]} ${suffix.slice(0, 80)}`);
    if (!negative && !optional && !company && required) return quoted;
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
    ["Go", /\bgolang\b|\b(?:experience|proficiency|expertise|development)\s+(?:with|in|using)\s+go\b|\b(?:tech(?:nology)?\s+stack|programming\s+languages?|languages?)\s*:?[^.\n]{0,80}\bgo\b|(?:^|[,(;/|])\s*go\s*(?=\s*(?:[,);/|]|$))/im], ["Java", /\bjava\b/i],
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
