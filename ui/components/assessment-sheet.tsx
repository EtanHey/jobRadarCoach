"use client";
import type { JobDetail } from "@/lib/contracts";
import { Button } from "./ui/button";
import { Sheet, SheetTrigger, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "./ui/sheet";

export function AssessmentSheet({job}: {job: JobDetail}) {
  return <Sheet><SheetTrigger render={<Button size="sm" variant="secondary" />} aria-label={job.score === null ? "Open AI assessment: not scored" : `Open AI assessment: fit score ${job.score} out of 100`}>
    {job.score === null ? "Not scored" : `${job.score}/100`}
  </SheetTrigger><SheetContent forceOverlay className="overflow-y-auto data-[side=right]:w-full data-[side=right]:sm:max-w-lg">
    <SheetHeader><SheetTitle>AI assessment</SheetTitle><SheetDescription>{job.title} at {job.company}</SheetDescription></SheetHeader>
    <div className="space-y-5 px-4 pb-6"><section className="rounded-xl border bg-muted/60 p-4"><h2 className="text-sm font-semibold">Fit assessment</h2><p className="mt-2 text-3xl font-semibold">{job.score === null ? "Not scored" : `${job.score} / 100`}</p>{job.fit_line && <p className="mt-3 whitespace-pre-wrap break-words text-sm leading-6">{job.fit_line}</p>}{job.recommendation && <p className="mt-2 text-sm capitalize">Recommendation: {job.recommendation}</p>}</section>
      {!!job.reasons.length && <section><h2 className="font-semibold">Why this score</h2><ul className="mt-3 space-y-3">{job.reasons.map((item) => <li key={item.factor} className="rounded-xl border bg-card p-4 text-sm"><span className="mb-1 block text-xs capitalize text-muted-foreground">{item.factor.replaceAll("_", " ")} · {item.assessment}</span><span className="whitespace-pre-wrap break-words">{item.detail}</span></li>)}</ul></section>}
    </div>
  </SheetContent></Sheet>;
}
