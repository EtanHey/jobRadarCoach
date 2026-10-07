"use client";
import { useId, useRef, useState, type ReactNode } from "react";
import { SlidersHorizontal } from "lucide-react";
import { Button } from "./ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "./ui/sheet";
import type { JobSummary } from "@/lib/contracts";
import { levelOrder, sourceFilterValues, type ViewOptions } from "@/lib/job-filters";
import { AppSelect, type SelectOption } from "@/components/ui/select";
import { PipelineStatusFilter } from "./pipeline-status-filter";

export function JobToolbar({ jobs, options, onChange, onReset, canReset = false, actions, globeOpen = false, filtersCollapsed = false, onFiltersCollapsedChange }: {
  jobs: JobSummary[]; options: ViewOptions; onChange: (next: ViewOptions) => void;
  onReset?: () => void; canReset?: boolean; actions?: ReactNode; globeOpen?: boolean;
  filtersCollapsed?: boolean; onFiltersCollapsedChange?: (collapsed: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const filtersId = useId();
  const opener = useRef<HTMLButtonElement | null>(null);
  const active = [options.work_mode !== undefined || options.remote !== undefined, options.source, options.location, options.seniority, options.fit, options.statuses.length > 0, options.availability !== "active", options.sort !== "fit", options.found_within].filter(Boolean).length;
  const fields: { key: "work_mode" | "source" | "location" | "seniority" | "fit" | "availability" | "sort"; label: string; choices: SelectOption[] }[] = [
    { key: "work_mode", label: "Work mode", choices: [{ value: "", label: "Any work mode" }, { value: "remote", label: "Remote" }, { value: "hybrid", label: "Hybrid" }, { value: "on-site", label: "On-site" }] },
    { key: "source", label: "Source", choices: [{value: "", label: "All sources"}, ...sourceFilterValues(jobs, options.source).map((source) => ({value: source, label: source}))] },
    { key: "location", label: "Location", choices: [{value: "", label: "All locations"}, {value: "israel", label: "Israel"}, {value: "united-states", label: "United States"}, {value: "other", label: "Other"}] },
    { key: "seniority", label: "Seniority", choices: [{value: "", label: "All levels"}, {value: "non-senior", label: "Hide senior+ (keep unknown)"}, ...levelOrder.map((level) => ({value: level, label: level}))] },
    { key: "fit", label: "Fit", choices: [{value: "", label: "Any fit"}, {value: "recommended", label: "Worth considering"}, {value: "skip", label: "Suggested skip"}, {value: "good", label: "60+ fit score"}, {value: "scored", label: "Scored"}, {value: "unscored", label: "Not scored"}] },
    { key: "availability", label: "Availability", choices: [{value: "active", label: "Active"}, {value: "inactive", label: "Inactive"}, {value: "all", label: "All"}] },
    { key: "sort", label: "Sort", choices: [{value: "found", label: "Recently found"}, {value: "posted", label: "Recently posted"}, {value: "fit", label: "Best fit first"}, {value: "seniority", label: "Seniority: junior first"}] },
  ] as const;
  const valueFor = (key: typeof fields[number]["key"]) => key === "work_mode"
    ? options.work_mode ?? (options.remote === true ? "remote" : options.remote === false ? "on-site" : "")
    : String(options[key] ?? "");
  const controls = (compact: boolean) => fields.flatMap(({key, label, choices}) => {
    const value = valueFor(key);
    const selectedLabel = (choices.find(choice => choice.value === value) ?? choices[0]).label;
    return [
      ...(key === "sort" ? [<div key="statuses" className={compact ? "w-[8rem] shrink-0" : ""}><PipelineStatusFilter value={options.statuses} onChange={(statuses) => onChange({ ...options, statuses })} /></div>] : []),
      <div key={key} className="min-w-0 shrink-0" style={compact ? { width: `clamp(6rem, ${(selectedLabel.length + 5) * 0.44}rem, 10rem)` } : undefined}><AppSelect compact label={label} value={value} options={choices} onValueChange={(next) => onChange(key === "work_mode" ? { ...options, remote: undefined, work_mode: next === "" ? undefined : next as ViewOptions["work_mode"] } : { ...options, [key]: next })} /></div>,
    ];
  });
  const foundWithin = <div role="group" aria-label="Found in the past" className="min-w-0 shrink-0">
    <span className="mb-1 block text-[11px] leading-4 text-muted-foreground">Found in the past</span>
    <div className="flex flex-wrap gap-1">
      {([ ["", "Any time"], ["24h", "24 h"], ["3d", "3 d"], ["7d", "7 d"], ["30d", "30 d"] ] as const).map(([value, label]) => <Button key={value} type="button" size="sm" className="h-10" variant={(options.found_within ?? "") === value ? "secondary" : "ghost"} aria-pressed={(options.found_within ?? "") === value} onClick={() => onChange({ ...options, found_within: value || undefined })}>{label}</Button>)}
    </div>
  </div>;
  const badge = active > 0 && <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground">{active}<span className="sr-only"> active</span></span>;
  return <div data-job-toolbar>
    <div role="group" aria-label="Found in the past" className="mb-2 flex flex-wrap items-center gap-1">
      <span className="mr-1 text-xs text-muted-foreground">Found in the past</span>
      {([ ["", "Any time"], ["24h", "24 h"], ["3d", "3 d"], ["7d", "7 d"], ["30d", "30 d"] ] as const).map(([value, label]) => <Button key={value} type="button" size="sm" variant={(options.found_within ?? "") === value ? "secondary" : "ghost"} aria-pressed={(options.found_within ?? "") === value} onClick={() => onChange({ ...options, found_within: value || undefined })}>{label}</Button>)}
    </div>
    <div className={`hidden flex-wrap items-end gap-2 pb-2 ${globeOpen ? "xl:flex" : "md:flex"}`}>
      <Button type="button" variant="outline" className="h-10" aria-expanded={!filtersCollapsed} aria-controls={filtersId} onClick={() => onFiltersCollapsedChange?.(!filtersCollapsed)}><SlidersHorizontal aria-hidden="true" />Filters{badge}</Button>
      <div id={filtersId} hidden={filtersCollapsed} className={filtersCollapsed ? "hidden" : "contents"}>{!filtersCollapsed && <>{controls(true)}{foundWithin}</>}</div>
      <div className="flex h-10 shrink-0 items-center gap-1"><Button type="button" variant="ghost" className="h-10" disabled={!canReset} onClick={onReset}>Reset view</Button>{actions}</div>
    </div>
    <div className={`flex flex-wrap items-center gap-2 pb-2 ${globeOpen ? "xl:hidden" : "md:hidden"}`}><Button ref={opener} variant="outline" onClick={() => setOpen(true)}><SlidersHorizontal aria-hidden="true" />Filters{badge}</Button><Button type="button" variant="ghost" className="h-10" disabled={!canReset} onClick={onReset}>Reset view</Button>{actions}</div>

    <Sheet open={open} onOpenChange={setOpen}><SheetContent finalFocus={opener} className="overflow-y-auto data-[side=right]:w-full">
      <SheetHeader><SheetTitle>Filters</SheetTitle><SheetDescription>Narrow the roles and choose their order.</SheetDescription></SheetHeader>
      <div className="grid gap-5 px-4">{controls(false)}{foundWithin}<Button onClick={() => setOpen(false)}>Show roles</Button></div>
    </SheetContent></Sheet>
  </div>;
}
