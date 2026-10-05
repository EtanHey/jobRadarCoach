"use client";

import type { ReactNode, RefObject } from "react";
import { Bookmark, Recycle } from "lucide-react";
import type { JobSummary } from "@/lib/contracts";
import { scoreCss } from "@/lib/globe-model";
import { repostNote, workMode } from "@/lib/job-display";
import { CompanyLogo } from "./company-logo";
import { InfoTip } from "./info-tip";
import { PostingDates } from "./posting-dates";

type Props = {
  job: JobSummary;
  alternateCount?: number;
  /** Alternates demonstrably listed before this one; drives the repost marker. */
  earlierListings?: number;
  selected?: boolean;
  actions?: ReactNode;
  openerRef: RefObject<HTMLButtonElement | null>;
  selectJob: (id: string | null) => void;
  children: ReactNode;
};

export function JobCard({ job, selected, actions, alternateCount = 0, earlierListings = 0, openerRef, selectJob, children }: Props) {
  const experience = job.experience ?? job.seniority ?? "Experience unspecified";
  const repost = repostNote(job.posted_at, job.last_published_at, earlierListings);
  return <article data-posting-id={job.id} className="relative flex w-full flex-col gap-3 rounded-xl border bg-card p-4 text-card-foreground shadow-sm transition-colors hover:border-ring/50 focus-within:ring-2 focus-within:ring-ring">
    <button type="button" aria-pressed={selected} aria-label={`Open ${job.title} at ${job.company}`} className="absolute inset-0 rounded-xl outline-none" onClick={event => { openerRef.current = event.currentTarget; selectJob(job.id); }} />
    <div className="pointer-events-none flex flex-wrap items-start gap-3">
      <CompanyLogo company={job.company} className="size-14 sm:size-16" />
      <div className="min-w-0 max-w-[28rem] flex-[1_1_9rem]">
        <div className="flex min-w-0 items-center gap-1.5 text-sm text-muted-foreground">
          <p className="truncate">{job.company}</p>
          {repost && <InfoTip data-repost-marker label={repost} tip={repost} className="shrink-0"><Recycle aria-hidden="true" size={13} /></InfoTip>}
        </div>
        <h2 className="mt-1 line-clamp-2 h-12 text-lg font-semibold leading-6 sm:h-14 sm:text-xl sm:leading-7" title={job.title}>{job.title}</h2>
      </div>
      <div className="flex shrink-0 flex-col items-end gap-1">
        <span style={job.score === null ? { border: "2px solid var(--globe-unscored-ring)" } : { backgroundColor: scoreCss(job.score), color: "#08111c" }} aria-label={job.score === null ? "Not scored" : `Fit score ${job.score} out of 100`} className={job.score === null ? "rounded-lg px-2 py-1 text-xs text-muted-foreground" : "rounded-lg px-2 py-1"}>
          {job.score === null ? "Unscored" : <><strong className="text-base tabular-nums">{job.score}</strong><span className="text-[10px]">/100</span></>}
        </span>
        {job.status === "worth_checking" && <Bookmark size={13} aria-label="Worth checking" className="text-muted-foreground" />}
      </div>
    </div>
    <p className="pointer-events-none truncate text-sm text-muted-foreground" title={`${job.location ?? "Location unspecified"} · ${workMode(job.remote)}`}>{job.location ?? "Location unspecified"} · {workMode(job.remote)}</p>
    <div className="pointer-events-none relative min-h-[3.625rem] text-muted-foreground [&_button]:pointer-events-auto">{job.stack.length ? children : <span className="text-xs">Stack unspecified</span>}</div>
    <div className="pointer-events-none mt-auto flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      <span data-experience className="min-w-0 break-words">{experience}</span>
      <div className="ml-auto flex min-w-0 flex-wrap items-center justify-end gap-x-2 gap-y-1">
        <PostingDates postedAt={job.posted_at} lastPublishedAt={job.last_published_at} firstSeenAt={job.first_seen_at} className="shrink-0" />
        <span className="shrink-0 capitalize">{job.source}</span>
        {alternateCount > 0 && <span className="shrink-0" title="Open to choose another listing">{alternateCount + 1} listings</span>}
      </div>
    </div>
    {actions && <div className="relative z-10">{actions}</div>}
  </article>;
}
