import type { JobSummary } from "./contracts";
import publishers from "./employer-publishers.json";
import aliases from "./employer-aliases.json";

const suffix = /(?:^| )(?:private limited|pvt ltd|inc|ltd|llc|corp|corporation|company|co|group|holdings|lab|labs|gmbh|ag|sa|bv|ai|technologies|systems)$/;

function core(name: string): string {
  // Caseless matching like Python casefold: preserve dotless i, expand sharp s.
  const folded = name.replace(/\([A-Z][A-Z0-9&.]{1,}\)/g, " ")
    .replace(/[^ı]/gu, char => char.toUpperCase().toLowerCase().replaceAll("ß", "ss"));
  let value = (folded.match(/[\p{L}\p{N}]+/gu) ?? []).join(" ");
  while (suffix.test(value)) value = value.replace(suffix, "");
  return value;
}

function isAlias(publisher: string, employer: string): boolean {
  const left = core(publisher), right = core(employer);
  return Boolean(left && right && (left === right || left.startsWith(right + " ") || right.startsWith(left + " ")))
    || Object.entries(aliases).some(([name, names]) =>
      name.toLowerCase() === publisher.toLowerCase()
      && names.some(alias => alias.toLowerCase() === employer.toLowerCase()));
}

export function employerLabel(job: Pick<JobSummary, "company" | "employer_identity">): string {
  const identity = job.employer_identity;
  const agency = publishers.some(name => name.toLowerCase() === job.company.toLowerCase())
    || (identity?.publisher === job.company && Boolean(identity.agency_evidence?.trim()));
  if (identity?.publisher === job.company) {
    if (!identity.hiring_employer) return agency ? `${job.company} (agency — client undisclosed)` : job.company;
    return identity.relationship === "alias" || isAlias(job.company, identity.hiring_employer)
      || identity.hiring_employer.toLowerCase() === job.company.toLowerCase()
      ? job.company : `${identity.hiring_employer} via ${job.company}`;
  }
  return agency
    ? `${job.company} (agency — client undisclosed)` : job.company;
}

export function employerName(job: Pick<JobSummary, "company" | "employer_identity">): string {
  return job.employer_identity?.publisher === job.company
    ? job.employer_identity.hiring_employer ?? job.company : job.company;
}
