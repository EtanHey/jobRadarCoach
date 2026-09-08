"use client";
import { useRef, useState } from "react";
import { SlidersHorizontal } from "lucide-react";
import { Button } from "./ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "./ui/sheet";
import type { JobSummary } from "@/lib/contracts";
import { levelOrder, sourceFilterValues, type ViewOptions } from "@/lib/job-filters";
import { AppSelect, type SelectOption } from "@/components/ui/select";
import { PipelineStatusFilter } from "./pipeline-status-filter";

export function JobToolbar({ jobs, options, onChange, onReset, canReset = false }: {
  jobs: JobSummary[]; options: ViewOptions; onChange: (next: ViewOptions) => void;
  onReset?: () => void; canReset?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const opener = useRef<HTMLButtonElement | null>(null);
  const active = [options.source, options.location, options.seniority, options.fit, options.statuses.length > 0, options.sort !== "fit"].filter(Boolean).length;
  const fields: { key: "source" | "location" | "seniority" | "fit" | "sort"; label: string; choices: SelectOption[] }[] = [
    { key: "source", label: "Source", choices: [{value: "", label: "All sources"}, ...sourceFilterValues(jobs, options.source).map((source) => ({value: source, label: source}))] },
    { key: "location", label: "Location", choices: [{value: "", label: "All locations"}, {value: "israel", label: "Israel"}, {value: "united-states", label: "United States"}, {value: "other", label: "Other"}] },
    { key: "seniority", label: "Seniority", choices: [{value: "", label: "All levels"}, {value: "non-senior", label: "Hide senior+ (keep unknown)"}, ...levelOrder.map((level) => ({value: level, label: level}))] },
    { key: "fit", label: "Fit", choices: [{value: "", label: "Any fit"}, {value: "recommended", label: "Worth considering"}, {value: "skip", label: "Suggested skip"}, {value: "good", label: "60+ fit score"}, {value: "scored", label: "Scored"}, {value: "unscored", label: "Not scored"}] },
    { key: "sort", label: "Sort", choices: [{value: "found", label: "Recently found"}, {value: "posted", label: "Recently posted"}, {value: "fit", label: "Best fit first"}, {value: "seniority", label: "Seniority: junior first"}] },
  ] as const;
  const controls = fields.flatMap(({key, label, choices}) => [
    ...(key === "sort" ? [<PipelineStatusFilter key="statuses" value={options.statuses} onChange={(statuses) => onChange({ ...options, statuses })} />] : []),
    <div key={key} className="min-w-0"><AppSelect label={label} value={options[key]} options={choices} onValueChange={(value) => onChange({ ...options, [key]: value })} /></div>,
  ]);
  return <>
    <div className="hidden pb-3 md:block"><div className="grid grid-cols-3 items-end gap-3 xl:grid-cols-6">{controls}</div><div className="mt-2 flex justify-end"><Button type="button" variant="ghost" disabled={!canReset} onClick={onReset}>Reset view</Button></div></div>
    <div className="flex gap-2 pb-3 md:hidden"><Button ref={opener} variant="outline" onClick={() => setOpen(true)}><SlidersHorizontal aria-hidden="true" />Filters{active > 0 && <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground">{active}<span className="sr-only"> active</span></span>}</Button><Button type="button" variant="ghost" disabled={!canReset} onClick={onReset}>Reset view</Button></div>
    <Sheet open={open} onOpenChange={setOpen}><SheetContent finalFocus={opener} className="overflow-y-auto data-[side=right]:w-full">
      <SheetHeader><SheetTitle>Filters</SheetTitle><SheetDescription>Narrow the roles and choose their order.</SheetDescription></SheetHeader>
      <div className="grid gap-5 px-4">{controls}<Button onClick={() => setOpen(false)}>Show roles</Button></div>
    </SheetContent></Sheet>
  </>;
}
