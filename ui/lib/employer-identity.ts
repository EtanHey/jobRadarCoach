import type { JobSummary } from "./contracts";
import publishers from "./employer-publishers.json";

export function employerLabel(job: Pick<JobSummary, "company" | "employer_identity">): string {
  const identity = job.employer_identity;
  if (identity?.publisher === job.company) {
    if (!identity.hiring_employer) return `${job.company} (agency — client undisclosed)`;
    return identity.hiring_employer.toLowerCase() === job.company.toLowerCase()
      ? job.company : `${identity.hiring_employer} via ${job.company}`;
  }
  return publishers.some(name => name.toLowerCase() === job.company.toLowerCase())
    ? `${job.company} (agency — client undisclosed)` : job.company;
}

export function employerName(job: Pick<JobSummary, "company" | "employer_identity">): string {
  return job.employer_identity?.publisher === job.company
    ? job.employer_identity.hiring_employer ?? job.company : job.company;
}
