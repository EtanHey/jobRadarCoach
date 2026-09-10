import type { Availability, JobSummary } from "./contracts";
import { groupDuplicateJobs, type DuplicateJobGroup } from "./job-dedup";
import { matchesFit } from "./job-fit";
import type { PipelineStatus } from "./job-status";

export type JobSort = "found" | "posted" | "fit" | "seniority";
export type LocationFilter = "" | "israel" | "united-states" | "other";
export type LocationGroup = Exclude<LocationFilter, ""> | "unknown";
export type ViewOptions = { search: string; source: string; location: LocationFilter; seniority: string; fit: string; statuses: PipelineStatus[]; availability: Availability; sort: JobSort };
export const levelOrder = ["Intern", "Junior", "Mid-level", "Senior", "Lead / Manager", "Staff / Principal", "Unknown"];
export function sourceFilterValues(jobs: Pick<JobSummary, "source">[], selected: string): string[] {
  return [...new Set([...jobs.map((job) => job.source), ...(selected ? [selected] : [])])].sort();
}
const ISRAEL_LOCATION = /\b(israel|tel aviv(?:-yafo)?|jerusalem|haifa|herzliya|petah tikva|ramat gan|ra['’]?anana|yavne|kfar saba|netanya|yokneam|beer sheva|be['’]?er sheva|caesarea|rehovot|hod hasharon|bnei brak)\b/i;
const UNITED_STATES_LOCATION = /\b(united states(?: of america)?|u\.?s\.?a?\.?)\b/i;
// A two-letter suffix alone can also be a country code (CA = Canada, IN = India).
const UNITED_STATES_CITIES: Record<string, readonly string[]> = {
  CA: ["San Francisco", "Los Angeles", "Cupertino", "Walnut Creek", "Hawthorne", "Fremont", "Mountain View", "Sunnyvale", "Calabasas"],
  NY: ["New York", "Medina", "Albany", "Brooklyn"], WA: ["Seattle", "Redmond", "Bellevue"],
  TX: ["Bastrop", "San Antonio", "Austin"], FL: ["Tampa", "Jacksonville", "Miami"],
  IL: ["Chicago", "Deer Park", "Lisle"], VA: ["McLean", "Reston"], OH: ["Celina", "West Chester", "Dayton"],
  PA: ["Philadelphia", "Williamsport", "Lititz", "Linden", "Wayne"], MI: ["Rochester Hills", "Whitehall", "Troy"],
  WI: ["Pound", "Madison"], CO: ["Denver", "Colorado Springs"], MA: ["Cambridge", "Boston"],
  MN: ["Maple Plain"], CT: ["Greenwich"], AR: ["Conway"], IN: ["Fortville"], GA: ["Atlanta"],
  NC: ["Charlotte"], NJ: ["South Plainfield"], WY: ["Cheyenne"], SC: ["Aiken"], TN: ["Memphis"],
  VT: ["South Burlington"], AZ: ["Scottsdale"], MD: ["Columbia"], DC: ["Washington"],
};
function knownUnitedStatesCity(location: string): boolean {
  const match = /^([^,]+),\s*([A-Z]{2})$/.exec(location);
  return !!match && !!UNITED_STATES_CITIES[match[2]]?.some((city) => city.toLowerCase() === match[1].trim().toLowerCase());
}
const UNITED_STATES_METRO = /^(?:san francisco bay area|new york city metropolitan area|greater (?:cleveland|chicago area)|(?:austin|san antonio), texas metropolitan area|columbia, south carolina metropolitan area)$/i;
const REMOTE_ONLY = /^(?:remote|hybrid|on[- ]?site|worldwide|anywhere)(?:\s+(?:role|position|work))?(?:(?:\s*[/|,·—–\-]\s*|\s+or\s+|\s+)(?:remote|hybrid|on[- ]?site|worldwide|anywhere)(?:\s+(?:role|position|work))?)*$/i;
export function locationGroup(value: string | null): LocationGroup {
  const location = value?.trim() ?? "";
  if (!location || REMOTE_ONLY.test(location)) return "unknown";
  if (ISRAEL_LOCATION.test(location)) return "israel";
  if (UNITED_STATES_LOCATION.test(location) || knownUnitedStatesCity(location) || UNITED_STATES_METRO.test(location)) return "united-states";
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
function matchesView(job: JobSummary, options: ViewOptions, needle: string): boolean {
  return (
    (!needle || [job.title, job.company, job.location, job.source, ...job.stack].join(" ").toLocaleLowerCase().includes(needle)) &&
    (!options.source || job.source === options.source) &&
    (!options.location || locationGroup(job.location) === options.location) &&
    (!options.seniority || (options.seniority === "non-senior" ? !["Senior", "Lead / Manager", "Staff / Principal"].includes(levelGroup(job.seniority)) : levelGroup(job.seniority) === options.seniority)) &&
    (options.statuses.length === 0 || options.statuses.includes(job.status as PipelineStatus)) &&
    matchesFit(job, options.fit)
  );
}
function compareJobs(a: JobSummary, b: JobSummary, sort: JobSort): number {
    if (sort === "fit") return (b.score ?? -1) - (a.score ?? -1) || timestamp(b.first_seen_at) - timestamp(a.first_seen_at);
    if (sort === "seniority") return levelOrder.indexOf(levelGroup(a.seniority)) - levelOrder.indexOf(levelGroup(b.seniority)) || a.title.localeCompare(b.title);
    if (sort === "posted") return timestamp(b.posted_at ?? b.first_seen_at) - timestamp(a.posted_at ?? a.first_seen_at);
    return timestamp(b.first_seen_at) - timestamp(a.first_seen_at);
}
export function filterJobs(jobs: JobSummary[], options: ViewOptions): JobSummary[] {
  const needle = options.search.trim().toLocaleLowerCase();
  return jobs.filter((job) => matchesView(job, options, needle))
    .sort((a, b) => compareJobs(a, b, options.sort));
}
export function filterJobGroups(jobs: JobSummary[], options: ViewOptions): DuplicateJobGroup[] {
  const needle = options.search.trim().toLocaleLowerCase();
  return groupDuplicateJobs(jobs.filter((job) => matchesView(job, options, needle)))
    .sort((a, b) => compareJobs(a.job, b.job, options.sort));
}
