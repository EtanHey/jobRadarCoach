import type { JobSummary } from "@/lib/contracts";

export function LinkedInClosureBadge({ job }: { job: Pick<JobSummary, "linkedin_closed_signal"> }) {
  const signal = job.linkedin_closed_signal;
  if (!signal) return null;
  return <a data-linkedin-closed-signal href={signal.url} target="_blank" rel="noopener noreferrer"
    className="relative z-10 block w-fit max-w-full rounded-md border border-amber-500/40 bg-amber-500/10 px-2 py-1 text-xs leading-relaxed text-foreground underline decoration-amber-500/60 underline-offset-2 hover:bg-amber-500/20 focus-visible:outline-2">
    LinkedIn: {signal.phrase} · checked <time dateTime={signal.checked_at}>{signal.checked_at.slice(0, 10)}</time>
  </a>;
}
