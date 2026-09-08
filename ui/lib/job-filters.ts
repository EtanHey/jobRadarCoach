import type { JobSummary } from "./contracts";
import { matchesFit } from "./job-fit";

export type JobSort = "found" | "posted" | "fit" | "seniority";
export type LocationFilter = "" | "israel" | "united-states" | "other";
export type LocationGroup = Exclude<LocationFilter, ""> | "unknown";
export type ViewOptions = { search: string; source: string; location: LocationFilter; seniority: string; fit: string; sort: JobSort };
export const levelOrder = ["Intern", "Junior", "Mid-level", "Senior", "Lead / Manager", "Staff / Principal", "Unknown"];
const ISRAEL_LOCATION = /\b(israel|tel aviv(?:-yafo)?|jerusalem|haifa|herzliya|petah tikva|ramat gan|ra['’]?anana|yavne|kfar saba|netanya|yokneam|beer sheva|be['’]?er sheva|caesarea|rehovot|hod hasharon|bnei brak)\b/i;
const UNITED_STATES_LOCATION = /\b(united states(?: of america)?|u\.?s\.?a?\.?)\b/i;
const UNITED_STATES_STATE = /,\s*(?:AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|VT|VA|WA|WV|WI|WY)(?:\b|$)/;
const UNITED_STATES_METRO = /\bsan francisco bay area\b/i;
const REMOTE_ONLY = /^(?:remote|hybrid|on[- ]?site|worldwide|anywhere)(?:\s+(?:role|position|work))?$/i;
export function locationGroup(value: string | null): LocationGroup {
  const location = value?.trim() ?? "";
  if (!location || REMOTE_ONLY.test(location)) return "unknown";
  if (ISRAEL_LOCATION.test(location)) return "israel";
  if (UNITED_STATES_LOCATION.test(location) || UNITED_STATES_STATE.test(location) || UNITED_STATES_METRO.test(location)) return "united-states";
  return "other";
}
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
    (!options.location || locationGroup(job.location) === options.location) &&
    (!options.seniority || (options.seniority === "non-senior" ? !["Senior", "Lead / Manager", "Staff / Principal"].includes(levelGroup(job.seniority)) : levelGroup(job.seniority) === options.seniority)) &&
    matchesFit(job, options.fit),
  ).sort((a, b) => {
    if (options.sort === "fit") return (b.score ?? -1) - (a.score ?? -1) || timestamp(b.first_seen_at) - timestamp(a.first_seen_at);
    if (options.sort === "seniority") return levelOrder.indexOf(levelGroup(a.seniority)) - levelOrder.indexOf(levelGroup(b.seniority)) || a.title.localeCompare(b.title);
    if (options.sort === "posted") return timestamp(b.posted_at ?? b.first_seen_at) - timestamp(a.posted_at ?? a.first_seen_at);
    return timestamp(b.first_seen_at) - timestamp(a.first_seen_at);
  });
}
