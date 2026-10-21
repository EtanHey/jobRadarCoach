import type { JobSummary } from "./contracts";
import publishers from "./employer-publishers.json";
import aliases from "./employer-aliases.json";

export function employerLabel(job: Pick<JobSummary, "company" | "employer_identity">): string {
  const identity = job.employer_identity;
  const agency = publishers.some(name => name.toLowerCase() === job.company.toLowerCase())
    || (identity?.publisher === job.company && Boolean(identity.agency_evidence?.trim()));
  if (identity?.publisher === job.company) {
    if (!identity.hiring_employer) return agency ? `${job.company} (agency — client undisclosed)` : job.company;
    return identity.relationship === "alias" || Object.entries(aliases).some(([publisher, names]) =>
      publisher.toLowerCase() === job.company.toLowerCase()
      && names.some(name => name.toLowerCase() === identity.hiring_employer?.toLowerCase()))
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
