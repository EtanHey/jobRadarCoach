import { z } from "zod";

export const VacancyIdentitySchema = z.object({
  requisitions: z.array(z.string().min(1)), jd_fingerprint: z.string().nullable(),
}).strict();
export type VacancyIdentity = z.infer<typeof VacancyIdentitySchema>;
type IdentityInput = { url: string; apply_url: string | null; raw_jd?: string | null };

function textRequisitions(text: string): string[] {
  const prose = text.replace(/https?:\/\/\S+/giu, " ");
  return [...prose.matchAll(/\bJR\d{5,}\b|\b(?:job\s+req(?:uisition)?\s+|req(?:uisition)?\.?(?:\s*(?:id|number|no\.?)\s*[:#-]?|\s*[:#-])\s*)(?=[A-Z\d_-]*\d)([A-Z\d]+(?:[-_][A-Z\d]+)*)\b/giu)]
    .map(match => (match[1] ?? match[0]).toUpperCase());
}

export function postingUrls(job: Pick<IdentityInput, "url" | "apply_url">): URL[] {
  return [...new Set([job.apply_url, job.url])].flatMap(value => {
    try { return value ? [new URL(value)] : []; } catch { return []; }
  });
}

// Only provider-specific posting fields can invalidate an explicit JD requisition.
function postingId(url: URL): string[] {
  try {
    const path = decodeURIComponent(url.pathname), host = url.hostname;
    const ids: string[] = [];
    const greenhouse = url.searchParams.get("gh_jid");
    if (greenhouse && /^\d+$/u.test(greenhouse)) ids.push(greenhouse);
    let match: RegExpMatchArray | null;
    if (/^(?:job-)?boards(?:\.eu)?\.greenhouse\.io$/u.test(host)
      && (match = path.match(/^\/[^/]+\/jobs\/(\d+)\/?$/u))) ids.push(match[1]);
    if (host === "jobs.lever.co"
      && (match = path.match(/^\/[^/]+\/([a-f\d]{8}(?:-[a-f\d]{4}){3}-[a-f\d]{12})(?:\/apply)?\/?$/iu))) ids.push(match[1]);
    if (host === "www.comeet.com"
      && (match = path.match(/^\/jobs\/[^/]+\/[^/]+\/([^/]+)(?:\/[^/]+)?\/?$/u))) ids.push(match[1]);
    if (host === "apply.workable.com"
      && (match = path.match(/^\/[^/]+\/(?:j\/([^/]+)\/?|jobs\/view\/([^/]+)\.md)$/u))) ids.push(match[1] ?? match[2]);
    if (/^(?:[a-z]{2,3}\.)?linkedin\.com$/u.test(host)) {
      if ((match = path.match(/^\/jobs\/view\/(?:[^/]*-)?(\d+)\/?$/u))) ids.push(match[1]);
      const current = url.searchParams.get("currentJobId");
      if (current && /^\d+$/u.test(current)) ids.push(current);
    }
    return ids;
  } catch { return []; }
}

export function vacancyIdentity(job: IdentityInput, urls = postingUrls(job)): VacancyIdentity {
  const postingIds = new Set(urls.flatMap(postingId).map(value => value.toUpperCase()));
  // A JR prefix on a numeric posting ID does not make it headcount evidence.
  const numericPostingIds = new Set([...postingIds].flatMap(value => value.match(/^(?:JR)?(\d+)$/u)?.[1] ?? []));
  const requisitions = new Set(textRequisitions(job.raw_jd ?? "").filter(value => {
    const number = value.match(/^(?:JR)?(\d+)$/u)?.[1];
    return !postingIds.has(value) && (!number || !numericPostingIds.has(number));
  }));
  for (const url of urls) {
    try {
      const path = decodeURIComponent(url.pathname);
      // ATS posting IDs identify source records, not employer headcount.
      if (url.hostname.endsWith(".myworkdayjobs.com")) {
        const workday = path.match(/_(JR\d+|R\d{5,})(?:-\d+)?(?:\/apply)?\/?$/iu);
        if (workday) requisitions.add(workday[1].toUpperCase());
      }
    } catch { /* Invalid legacy URLs supply no identity evidence. */ }
  }
  return { requisitions: [...requisitions].sort(), jd_fingerprint: jdFingerprint(job.raw_jd) };
}

export function jdFingerprint(description: string | null | undefined): string | null {
  // Strip standalone EEO/accommodation paragraphs, never arbitrary employer prose.
  const body = (description ?? "").normalize("NFKC")
    .replace(/<\/?(?:p|br|div|span|li|ul|ol|strong|em|b|i|h[1-6])(?:\s[^>]*)?\/?>/giu, " ").replace(/&nbsp;|&#160;/giu, " ")
    .replace(/\[([^\]]+)\]\([^)]*\)/gu, "$1").replace(/(\*\*|__)(.*?)\1/gu, "$2").replace(/`([^`]+)`/gu, "$1").replace(/(^|\n)#{1,6}\s+/gu, "$1")
    .split(/\n\s*\n/u).filter(paragraph => !/^\s*(?:we are an equal opportunity employer\b|equal (?:employment )?opportunity (?:employer|statement)\b|if you (?:need|require) (?:a reasonable )?accommodation\b)/iu.test(paragraph))
    .join(" ").replace(/\s+/gu, " ").trim().toLowerCase();
  // Frozen 658-row snapshot: only two nonempty normalized bodies fall below 400.
  // Short snippets are too weak to establish identity across title/location drift.
  if (body.length < 400) return null;
  // Two independent 32-bit hashes plus length; synchronous on server and browser.
  let a = 0x811c9dc5, b = 0x9e3779b9;
  for (let index = 0; index < body.length; index += 1) {
    const code = body.charCodeAt(index);
    a = Math.imul(a ^ code, 0x01000193);
    b = Math.imul(b ^ code, 0x85ebca6b);
  }
  return `jd1:${body.length}:${(a >>> 0).toString(16)}:${(b >>> 0).toString(16)}`;
}
