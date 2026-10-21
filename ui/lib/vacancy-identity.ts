import { z } from "zod";

export const VacancyIdentitySchema = z.object({
  requisitions: z.array(z.string().min(1)), jd_fingerprint: z.string().nullable(),
}).strict();
export type VacancyIdentity = z.infer<typeof VacancyIdentitySchema>;
type IdentityInput = { url: string; apply_url: string | null; raw_jd?: string | null };

function textRequisitions(text: string): string[] {
  return [...text.matchAll(/\bJR\d{5,}\b|\b(?:req(?:uisition)?\.?\s*(?:id|number|no\.?)|job\s*(?:req(?:uisition)?(?:\s*(?:id|number|no\.?))?|id|number|no\.?))\s*[:#-]?\s*(?=[A-Z\d_-]*\d)([A-Z\d]+(?:[-_][A-Z\d]+)*)\b/giu)]
    .map(match => (match[1] ?? match[0]).toUpperCase());
}

export function postingUrls(job: Pick<IdentityInput, "url" | "apply_url">): URL[] {
  return [...new Set([job.apply_url, job.url])].flatMap(value => {
    try { return value ? [new URL(value)] : []; } catch { return []; }
  });
}

export function vacancyIdentity(job: IdentityInput, urls = postingUrls(job)): VacancyIdentity {
  const requisitions = new Set(textRequisitions(job.raw_jd ?? ""));
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
  if (!body) return null;
  // Two independent 32-bit hashes plus length; synchronous on server and browser.
  let a = 0x811c9dc5, b = 0x9e3779b9;
  for (let index = 0; index < body.length; index += 1) {
    const code = body.charCodeAt(index);
    a = Math.imul(a ^ code, 0x01000193);
    b = Math.imul(b ^ code, 0x85ebca6b);
  }
  return `jd1:${body.length}:${(a >>> 0).toString(16)}:${(b >>> 0).toString(16)}`;
}
