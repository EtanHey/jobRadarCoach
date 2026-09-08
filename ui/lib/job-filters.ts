import type { JobSummary } from "./contracts";

export type JobSort = "found" | "posted" | "fit" | "seniority";
export type ViewOptions = { search: string; source: string; seniority: string; fit: string; sort: JobSort };
export const levelOrder = ["Intern", "Junior", "Mid-level", "Senior", "Lead / Manager", "Staff / Principal", "Unknown"];
export function levelGroup(value: string | null): string {
  if (!value) return "Unknown";
  if (/intern/i.test(value)) return "Intern";
  if (/junior|entry|graduate/i.test(value)) return "Junior";
  if (/staff|principal/i.test(value)) return "Staff / Principal";
  if (/lead|manager|director|head/i.test(value)) return "Lead / Manager";
  if (/senior/i.test(value)) return "Senior";
  if (/mid|intermediate/i.test(value)) return "Mid-level";
  return "Unknown";
}
function timestamp(value: string | null): number { return value ? Date.parse(value) || 0 : 0; }
export function filterJobs(jobs: JobSummary[], options: ViewOptions): JobSummary[] {
  const needle = options.search.trim().toLocaleLowerCase();
  return jobs.filter((job) =>
    (!needle || [job.title, job.company, job.location, job.source, ...job.stack].join(" ").toLocaleLowerCase().includes(needle)) &&
    (!options.source || job.source === options.source) &&
    (!options.seniority || (options.seniority === "non-senior" ? !["Senior", "Lead / Manager", "Staff / Principal"].includes(levelGroup(job.seniority)) : levelGroup(job.seniority) === options.seniority)) &&
    (!options.fit || (options.fit === "unscored" ? job.score === null : options.fit === "scored" ? job.score !== null : job.score !== null && job.score >= 60)),
  ).sort((a, b) => {
    if (options.sort === "fit") return (b.score ?? -1) - (a.score ?? -1) || timestamp(b.first_seen_at) - timestamp(a.first_seen_at);
    if (options.sort === "seniority") return levelOrder.indexOf(levelGroup(a.seniority)) - levelOrder.indexOf(levelGroup(b.seniority)) || a.title.localeCompare(b.title);
    if (options.sort === "posted") return timestamp(b.posted_at ?? b.first_seen_at) - timestamp(a.posted_at ?? a.first_seen_at);
    return timestamp(b.first_seen_at) - timestamp(a.first_seen_at);
  });
}
