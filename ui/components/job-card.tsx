"use client";

import type { ReactNode, RefObject } from "react";
import { Bookmark } from "lucide-react";
import type { JobSummary } from "@/lib/contracts";
import { publishedAge, workMode } from "@/lib/job-display";
import { CompanyLogo } from "./company-logo";

type Props = {
  job: JobSummary;
  alternateCount?: number;
  openerRef: RefObject<HTMLButtonElement | null>;
  selectJob: (id: string | null) => void;
  children: ReactNode;
};

export function JobCard({ job, alternateCount = 0, openerRef, selectJob, children }: Props) {
  const experience = job.experience ?? job.seniority ?? "Experience unspecified";
  return <article data-posting-id={job.id} className="relative flex w-full flex-col gap-3 rounded-xl border bg-card p-4 text-card-foreground shadow-sm transition-colors hover:border-ring/50 focus-within:ring-2 focus-within:ring-ring">
    <button type="button" aria-label={`Open ${job.title} at ${job.company}`} className="absolute inset-0 rounded-xl outline-none" onClick={event => { openerRef.current = event.currentTarget; selectJob(job.id); }} />
    <div className="pointer-events-none flex items-start gap-3">
      <CompanyLogo company={job.company} className="size-14 sm:size-16" />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm text-muted-foreground">{job.company}</p>
        <h2 className="mt-1 line-clamp-2 h-12 text-lg font-semibold leading-6 sm:h-14 sm:text-xl sm:leading-7" title={job.title}>{job.title}</h2>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <span aria-label={job.score === null ? "Not scored" : `Fit score ${job.score} out of 100`} className={job.score === null ? "rounded-lg bg-muted px-2 py-1 text-xs text-muted-foreground" : "rounded-lg bg-primary px-2 py-1 text-primary-foreground"}>
          {job.score === null ? "Unscored" : <><strong className="text-base tabular-nums">{job.score}</strong><span className="text-[10px]">/100</span></>}
        </span>
        {job.status === "worth_checking" && <Bookmark size={13} aria-label="Worth checking" className="text-muted-foreground" />}
      </div>
    </div>
    <p className="pointer-events-none truncate text-sm text-muted-foreground" title={`${job.location ?? "Location unspecified"} · ${workMode(job.remote)}`}>{job.location ?? "Location unspecified"} · {workMode(job.remote)}</p>
    <div className="pointer-events-none relative min-h-[3.625rem] text-muted-foreground [&_button]:pointer-events-auto">{job.stack.length ? children : <span className="text-xs">Stack unspecified</span>}</div>
    <div className="pointer-events-none mt-auto flex min-w-0 items-center gap-2 text-xs text-muted-foreground">
      <span className="min-w-0 flex-1 truncate" title={experience}>{experience}</span>
      <span className="shrink-0" title={job.posted_at ?? undefined}>{publishedAge(job.posted_at)}</span>
      <span className="shrink-0 capitalize">{job.source}</span>
      {alternateCount > 0 && <span className="shrink-0" title="Open to choose another listing">{alternateCount + 1} listings</span>}
    </div>
  </article>;
}
