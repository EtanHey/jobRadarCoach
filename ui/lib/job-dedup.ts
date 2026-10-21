import type { ListingPublicationEvidence } from "./job-display";
import { timestamp } from "./job-time";
import type { JobSummary } from "./contracts";
import { createRepostLocationMatcher } from "./repost-locations";
import { uniqueJobsById } from "./job-board-state";
import { postingUrls, vacancyIdentity, type VacancyIdentity } from "./vacancy-identity";

import type { GlobeJob } from "./globe-contract";
export type DuplicateJobGroup<T extends GlobeJob = JobSummary> = { job: T & ListingPublicationEvidence; alternates: T[] };

export function normalizedIdentity(value: string): string {
  return value.normalize("NFKC").trim().replace(/\s+/gu, " ").toLowerCase();
}

// Only known role-specific routes: no generic careers/homepage URL identities.
function roleKey(value: URL): string | null {
  try {
    const { hostname: host, pathname: path } = value;
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

function roleKeys(urls: URL[]): string[] {
  return [...new Set(urls.map(roleKey).filter((key): key is string => key !== null))];
}

type PreparedJob<T extends GlobeJob = GlobeJob> = { job: T; company: string; title: string; keys: string[]; identity: VacancyIdentity };
function sameRole(a: PreparedJob, b: PreparedJob, locationsMatch: ReturnType<typeof createRepostLocationMatcher>): boolean {
  if (!a.company || a.company !== b.company) return false;
  const left = a.identity, right = b.identity;
  if (left.requisitions.length > 1 || right.requisitions.length > 1) return false;
  if (left.requisitions.length && right.requisitions.length) return left.requisitions[0] === right.requisitions[0];
  if (!left.requisitions.length && !right.requisitions.length && left.jd_fingerprint && right.jd_fingerprint) {
    return left.jd_fingerprint === right.jd_fingerprint;
  }
  if (!locationsMatch(a.job.location, b.job.location)) return false;
  return a.keys.some(key => b.keys.includes(key)) || Boolean(a.title && a.title === b.title);
}

function newestFirst(a: GlobeJob, b: GlobeJob): number {
  const timeA = timestamp(a.posted_at) ?? timestamp(a.first_seen_at) ?? -Infinity;
  const timeB = timestamp(b.posted_at) ?? timestamp(b.first_seen_at) ?? -Infinity;
  return (timeA === timeB ? 0 : timeA > timeB ? -1 : 1)
    || (a.id < b.id ? -1 : a.id > b.id ? 1 : 0);
}

export function linkedPublicationDates(jobs: GlobeJob[]): Pick<JobSummary, "posted_at" | "last_published_at"> {
  const originals = jobs.map(job => job.posted_at).filter((date): date is string => timestamp(date) !== null);
  const publications = jobs.flatMap(job => [job.posted_at, job.last_published_at])
    .filter((date): date is string => timestamp(date) !== null);
  originals.sort((a, b) => Date.parse(a) - Date.parse(b));
  publications.sort((a, b) => Date.parse(b) - Date.parse(a));
  return { posted_at: originals[0] ?? null, last_published_at: publications[0] ?? null };
}

export function groupDuplicateJobs<T extends GlobeJob>(jobs: T[]): DuplicateJobGroup<T>[] {
  const buckets = new Map<string, PreparedJob<T>[]>();
  const locationsMatch = createRepostLocationMatcher();
  for (const job of uniqueJobsById(jobs)) {
    const key = normalizedIdentity(job.company);
    const urls = postingUrls(job);
    const prepared = { job, company: key, title: normalizedIdentity(job.title), keys: roleKeys(urls), identity: job.vacancy_identity ?? vacancyIdentity(job, urls) };
    const bucket = buckets.get(key);
    if (bucket) bucket.push(prepared); else buckets.set(key, [prepared]);
  }
  return [...buckets.values()].flatMap(bucket => {
    const groups: PreparedJob<T>[][] = [];
    // Strong evidence groups first; weak rows must not split a known vacancy.
    const strength = (job: PreparedJob) => job.identity.requisitions.length ? 2 : job.identity.jd_fingerprint ? 1 : 0;
    // Complete linkage prevents unknown-evidence bridges from merging distinct vacancies.
    for (const job of bucket.sort((a, b) => strength(b) - strength(a) || a.job.id.localeCompare(b.job.id))) {
      const group = groups.find(members => members.every(member => sameRole(member, job, locationsMatch)));
      if (group) group.push(job); else groups.push([job]);
    }
    return groups.map(members => {
      const listings = members.map(member => member.job).sort(newestFirst);
      const [job, ...alternates] = listings;
      return { job: alternates.length ? { ...job,
        listing_publication_dates: {
          posted_at: job.posted_at, last_published_at: job.last_published_at,
        }, ...linkedPublicationDates(listings) } : job, alternates };
    });
  });
}

export function relatedDuplicateJobs(
  jobs: GlobeJob[], selectedId: string, loadedDetail: GlobeJob | null,
): GlobeJob[] {
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
