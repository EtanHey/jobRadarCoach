import { timestamp } from "./job-time";
import type { JobSummary } from "./contracts";
import { createRepostLocationMatcher } from "./repost-locations";
import { uniqueJobsById } from "./job-board-state";

export type DuplicateJobGroup = { job: JobSummary; alternates: JobSummary[] };

function normalizedIdentity(value: string): string {
  return value.normalize("NFKC").trim().replace(/\s+/gu, " ").toLowerCase();
}

// Only known role-specific routes: no generic careers/homepage URL identities.
function roleKey(value: string | null): string | null {
  if (!value) return null;
  try {
    const { hostname: host, pathname: path } = new URL(value);
    let match: RegExpMatchArray | null;
    if (/^(?:job-)?boards(?:\.eu)?\.greenhouse\.io$/u.test(host)
      && (match = path.match(/^\/([^/]+)\/jobs\/(\d+)\/?$/u))) {
      return `greenhouse:${host.includes(".eu.") ? "eu" : "us"}:${match[1]}:${match[2]}`;
    }
    if (host === "apply.workable.com"
      && (match = path.match(/^\/([^/]+)\/(?:j\/([^/]+)\/?|jobs\/view\/([^/]+)\.md)$/u))) {
      return `workable:${match[1]}:${match[2] ?? match[3]}`;
    }
    if (host === "jobs.lever.co" && (match = path.match(/^\/([^/]+)\/([a-f0-9-]{36})(?:\/apply)?\/?$/u))) {
      return `lever:${match[1]}:${match[2]}`;
    }
    if (host === "www.comeet.com" && (match = path.match(/^\/jobs\/([^/]+)\/([^/]+)\/([^/]+)(?:\/[^/]+)?\/?$/u))) {
      return `comeet:${match[1]}:${match[2]}:${match[3]}`;
    }
    if (/^(?:www|il)\.linkedin\.com$/u.test(host)
      && (match = path.match(/^\/jobs\/view\/(?:[^/]*-)?(\d+)\/?$/u))) return `linkedin:${match[1]}`;
  } catch { /* Invalid legacy links provide no identity evidence. */ }
  return null;
}

function roleKeys(job: JobSummary): string[] {
  return [...new Set([roleKey(job.apply_url), roleKey(job.url)].filter((key): key is string => key !== null))];
}

type PreparedJob = { job: JobSummary; company: string; title: string; keys: string[] };
function sameRole(a: PreparedJob, b: PreparedJob, locationsMatch: ReturnType<typeof createRepostLocationMatcher>): boolean {
  if (!a.company || a.company !== b.company) return false;
  if (!locationsMatch(a.job.location, b.job.location)) return false;
  return a.keys.some(key => b.keys.includes(key)) || Boolean(a.title && a.title === b.title);
}

function newestFirst(a: JobSummary, b: JobSummary): number {
  const timeA = timestamp(a.posted_at) ?? timestamp(a.first_seen_at) ?? -Infinity;
  const timeB = timestamp(b.posted_at) ?? timestamp(b.first_seen_at) ?? -Infinity;
  return (timeA === timeB ? 0 : timeA > timeB ? -1 : 1)
    || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

export function linkedPublicationDates(jobs: JobSummary[]): Pick<JobSummary, "posted_at" | "last_published_at"> {
  const originals = jobs.map(job => job.posted_at).filter((date): date is string => timestamp(date) !== null);
  const publications = jobs.flatMap(job => [job.posted_at, job.last_published_at])
    .filter((date): date is string => timestamp(date) !== null);
  originals.sort((a, b) => Date.parse(a) - Date.parse(b));
  publications.sort((a, b) => Date.parse(b) - Date.parse(a));
  return { posted_at: originals[0] ?? null, last_published_at: publications[0] ?? null };
}

function isEarlier(alternate: JobSummary, job: JobSummary, discoveryFallback: boolean): boolean {
  const posted = [timestamp(alternate.posted_at), timestamp(job.posted_at)];
  if (posted[0] !== null && posted[1] !== null) return posted[0] < posted[1];
  if (!discoveryFallback) return false; // mixed or unparseable chronology is not evidence
  const seen = [timestamp(alternate.first_seen_at), timestamp(job.first_seen_at)];
  return seen[0] !== null && seen[1] !== null && seen[0] < seen[1];
}

// Alternates that were demonstrably published (or, when no listing has any publish date, found) before `job`.
// Same-instant twins and unknown chronology are alternative listings, not evidence of a repost.
export function earlierListingCount(job: JobSummary, alternates: JobSummary[]): number {
  const discoveryFallback = [job, ...alternates].every(listing => listing.posted_at === null && (listing.last_published_at ?? null) === null);
  return alternates.filter(alternate => isEarlier(alternate, job, discoveryFallback)).length;
}

export function groupDuplicateJobs(jobs: JobSummary[]): DuplicateJobGroup[] {
  const buckets = new Map<string, PreparedJob[]>();
  const locationsMatch = createRepostLocationMatcher();
  for (const job of uniqueJobsById(jobs)) {
    const key = normalizedIdentity(job.company);
    const prepared = { job, company: key, title: normalizedIdentity(job.title), keys: roleKeys(job) };
    const bucket = buckets.get(key);
    if (bucket) bucket.push(prepared); else buckets.set(key, [prepared]);
  }
  return [...buckets.values()].flatMap(bucket => {
    const groups: PreparedJob[][] = [];
    // Complete linkage prevents missing-location bridges from merging different cities.
    for (const job of bucket.sort((a, b) => a.job.id.localeCompare(b.job.id))) {
      const group = groups.find(members => members.every(member => sameRole(member, job, locationsMatch)));
      if (group) group.push(job); else groups.push([job]);
    }
    return groups.map(members => {
      const listings = members.map(member => member.job).sort(newestFirst);
      const [job, ...alternates] = listings;
      return { job: alternates.length ? { ...job, ...linkedPublicationDates(listings) } : job, alternates };
    });
  });
}

export function relatedDuplicateJobs(
  jobs: JobSummary[], selectedId: string, loadedDetail: JobSummary | null,
): JobSummary[] {
  const selected = loadedDetail?.id === selectedId ? loadedDetail : jobs.find(job => job.id === selectedId);
  if (!selected) return [];
  const group = groupDuplicateJobs([...jobs.filter(job => job.id !== selectedId), selected])
    .find(({ job, alternates }) => job.id === selectedId || alternates.some(job => job.id === selectedId));
  const ids = new Set(group ? [group.job, ...group.alternates].map(job => job.id) : []);
  return uniqueJobsById(jobs).filter(job => job.id !== selectedId && ids.has(job.id)).sort(newestFirst);
}

export function shortListingId(id: string): string {
  return id.slice(-8);
}
