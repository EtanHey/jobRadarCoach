import type { JobSummary } from "./contracts";
import { compatibleRepostLocations } from "./repost-locations";
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

function sameRole(a: JobSummary, b: JobSummary): boolean {
  const company = normalizedIdentity(a.company);
  if (!company || company !== normalizedIdentity(b.company)) return false;
  if (!compatibleRepostLocations(a.location, b.location)) return false;
  if (roleKeys(a).some(key => roleKeys(b).includes(key))) return true;
  const title = normalizedIdentity(a.title);
  return Boolean(title && title === normalizedIdentity(b.title));
}

function timestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
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

export function groupDuplicateJobs(jobs: JobSummary[]): DuplicateJobGroup[] {
  const buckets = new Map<string, JobSummary[]>();
  for (const job of uniqueJobsById(jobs)) {
    const key = normalizedIdentity(job.company);
    buckets.set(key, [...(buckets.get(key) ?? []), job]);
  }
  return [...buckets.values()].flatMap(bucket => {
    const groups: JobSummary[][] = [];
    // Complete linkage prevents missing-location bridges from merging different cities.
    for (const job of bucket.sort((a, b) => a.id.localeCompare(b.id))) {
      const group = groups.find(members => members.every(member => sameRole(member, job)));
      if (group) group.push(job); else groups.push([job]);
    }
    return groups.map(members => {
      const [job, ...alternates] = members.sort(newestFirst);
      return { job: alternates.length ? { ...job, ...linkedPublicationDates(members) } : job, alternates };
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
