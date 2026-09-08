import type { JobSummary } from "./contracts";

/** Recommendations and score are distinct: a stretch role can still merit review. */
export function matchesFit(job: Pick<JobSummary, "score" | "recommendation">, filter: string): boolean {
  switch (filter) {
    case "": return true;
    case "recommended": return job.score !== null && ["apply", "referral", "review"].includes(job.recommendation ?? "");
    case "skip": return job.score !== null && job.recommendation === "skip";
    case "good": return job.score !== null && job.score >= 60;
    case "scored": return job.score !== null;
    case "unscored": return job.score === null;
    default: return false;
  }
}
