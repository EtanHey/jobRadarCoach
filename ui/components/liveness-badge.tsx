import type { JobSummary } from "../lib/contracts";
import { livenessLabel } from "../lib/liveness";

export function LivenessBadge({ job, now }: { job: Pick<JobSummary, "liveness">; now?: number }) {
  const evidence = job.liveness;
  if (!evidence) return null;
  return <p className="pointer-events-none text-xs text-muted-foreground" title={evidence.state === "stale" ? "Latest availability unconfirmed" : undefined}>
    {livenessLabel(evidence, now)}
  </p>;
}
