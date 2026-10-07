"use client";
import { useId, useRef, useState, type ReactNode } from "react";
import { SlidersHorizontal, X } from "lucide-react";
import { Button } from "./ui/button";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription } from "./ui/sheet";
import type { JobSummary } from "@/lib/contracts";
import { levelOrder, sourceFilterValues, type ViewOptions } from "@/lib/job-filters";
import { AppSelect, type SelectOption } from "@/components/ui/select";
import { statusLabels } from "@/lib/job-status";
import { DEFAULT_BOARD_PREFERENCES, preferencesForBoardFilter, viewForBoardQuery, type BoardFilter } from "@/lib/job-board-preferences";
import { PipelineStatusFilter } from "./pipeline-status-filter";

export function JobToolbar({ jobs, options, effectiveOptions = options, filter = DEFAULT_BOARD_PREFERENCES.filter, onChange, onReset, canReset = false, actions, globeOpen = false, filtersCollapsed = false, onFiltersCollapsedChange }: {
  jobs: JobSummary[]; options: ViewOptions; effectiveOptions?: ViewOptions; filter?: BoardFilter; onChange: (next: ViewOptions) => void;
  onReset?: () => void; canReset?: boolean; actions?: ReactNode; globeOpen?: boolean;
  filtersCollapsed?: boolean; onFiltersCollapsedChange?: (collapsed: boolean) => void;
}) {
  const [open, setOpen] = useState(false);
  const filtersId = useId();
  const opener = useRef<HTMLButtonElement | null>(null);
  const fields: { key: "work_mode" | "source" | "location" | "seniority" | "fit" | "availability" | "sort"; label: string; choices: SelectOption[] }[] = [
    { key: "work_mode", label: "Work mode", choices: [{ value: "", label: "Any work mode" }, { value: "remote", label: "Remote" }, { value: "hybrid", label: "Hybrid" }, { value: "on-site", label: "On-site" }] },
    { key: "source", label: "Source", choices: [{value: "", label: "All sources"}, ...sourceFilterValues(jobs, options.source).map((source) => ({value: source, label: source}))] },
    { key: "location", label: "Location", choices: [{value: "", label: "All locations"}, {value: "israel", label: "Israel"}, {value: "united-states", label: "United States"}, {value: "other", label: "Other"}] },
    { key: "seniority", label: "Seniority", choices: [{value: "", label: "All levels"}, {value: "non-senior", label: "Hide senior+ (keep unknown)"}, ...levelOrder.map((level) => ({value: level, label: level}))] },
    { key: "fit", label: "Fit", choices: [{value: "", label: "Any fit"}, {value: "recommended", label: "Worth considering"}, {value: "skip", label: "Suggested skip"}, {value: "good", label: "60+ fit score"}, {value: "scored", label: "Scored"}, {value: "unscored", label: "Not scored"}] },
    { key: "availability", label: "Availability", choices: [{value: "active", label: "Active"}, {value: "inactive", label: "Inactive"}, {value: "all", label: "All"}] },
    { key: "sort", label: "Sort", choices: [{value: "found", label: "Recently found"}, {value: "posted", label: "Recently posted"}, {value: "fit", label: "Best fit first"}, {value: "seniority", label: "Seniority: junior first"}] },
  ] as const;
  const valueFor = (key: typeof fields[number]["key"], view = options) => key === "work_mode"
    ? view.work_mode ?? (view.remote === true ? "remote" : view.remote === false ? "on-site" : "")
    : String(view[key] ?? "");
  const windows = [["", "Any time"], ["24h", "24 h"], ["3d", "3 d"], ["7d", "7 d"], ["30d", "30 d"]] as const;
  // Summaries describe the query; clear actions edit saved options so archive
  // overrides never overwrite the ordinary view preferences.
  const defaults = viewForBoardQuery(preferencesForBoardFilter(DEFAULT_BOARD_PREFERENCES, filter));
  const selections = fields.flatMap(({ key, label, choices }) => {
    if (key === "sort") return [];
    const value = valueFor(key, effectiveOptions);
    const defaultValue = valueFor(key, defaults);
    if (value === defaultValue) return [];
    const selectedLabel = (choices.find(choice => choice.value === value) ?? choices[0]).label;
    return [{ key, label: `${label}: ${selectedLabel}`, clear: () => onChange(key === "work_mode"
      ? { ...options, remote: defaults.remote, work_mode: defaults.work_mode }
      : { ...options, [key]: defaultValue }) }];
  });
  const activeSelections = [
    ...selections,
    ...(effectiveOptions.statuses.length ? [{ key: "statuses", label: `Pipeline status: ${effectiveOptions.statuses.map(status => statusLabels[status]).join(", ")}`, clear: () => onChange({ ...options, statuses: [] }) }] : []),
    ...(effectiveOptions.found_within ? [{ key: "found_within", label: `Found: past ${effectiveOptions.found_within === "24h" ? "24 hours" : `${effectiveOptions.found_within.replace("d", "")} days`}`, clear: () => onChange({ ...options, found_within: undefined }) }] : []),
  ];
  const chips = <div aria-label="Active filters" className="flex min-w-0 flex-wrap items-center gap-1">
    {activeSelections.map(selection => <button key={selection.key} type="button" aria-label={`Clear ${selection.label}`} title={`Clear ${selection.label}`} onClick={selection.clear} className="inline-flex min-h-10 max-w-full items-center gap-1 rounded-full border bg-muted px-2 py-1 text-left text-xs focus-visible:outline-2 focus-visible:outline-offset-2">
      <span className="min-w-0 break-words">{selection.label}</span><X aria-hidden="true" className="size-3 shrink-0" />
    </button>)}
  </div>;
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
      {windows.map(([value, label]) => <Button key={value} type="button" size="sm" className="h-10" variant={(options.found_within ?? "") === value ? "secondary" : "ghost"} aria-pressed={(options.found_within ?? "") === value} onClick={() => onChange({ ...options, found_within: value || undefined })}>{label}</Button>)}
    </div>
  </div>;
  const badge = activeSelections.length > 0 && <span className="rounded-full bg-primary px-1.5 text-xs text-primary-foreground">{activeSelections.length}<span className="sr-only"> active</span></span>;
  return <div data-job-toolbar>
    <div className={`hidden flex-wrap items-end gap-2 pb-2 ${globeOpen ? "xl:flex" : "md:flex"}`}>
      <Button type="button" variant="outline" className="h-10" aria-expanded={!filtersCollapsed} aria-controls={filtersId} onClick={() => onFiltersCollapsedChange?.(!filtersCollapsed)}><SlidersHorizontal aria-hidden="true" />Filters{badge}</Button>
      {filtersCollapsed && chips}
      <div id={filtersId} hidden={filtersCollapsed} className={filtersCollapsed ? "hidden" : "contents"}>{!filtersCollapsed && <>{controls(true)}{foundWithin}</>}</div>
      <div className="flex h-10 shrink-0 items-center gap-1"><Button type="button" variant="ghost" className="h-10" disabled={!canReset} onClick={onReset}>Reset view</Button>{actions}</div>
    </div>
    <div className={`flex flex-wrap items-center gap-2 pb-2 ${globeOpen ? "xl:hidden" : "md:hidden"}`}><Button ref={opener} variant="outline" aria-expanded={open} onClick={() => setOpen(true)}><SlidersHorizontal aria-hidden="true" />Filters{badge}</Button>{!open && chips}<Button type="button" variant="ghost" className="h-10" disabled={!canReset} onClick={onReset}>Reset view</Button>{actions}</div>
    <Sheet open={open} onOpenChange={setOpen}><SheetContent finalFocus={opener} className="overflow-y-auto data-[side=right]:w-full">
      <SheetHeader><SheetTitle>Filters</SheetTitle><SheetDescription>Narrow the roles and choose their order. {activeSelections.length} active {activeSelections.length === 1 ? "filter" : "filters"}.</SheetDescription></SheetHeader>
      <div className="grid gap-5 px-4">{controls(false)}{foundWithin}<Button onClick={() => setOpen(false)}>Show roles</Button></div>
    </SheetContent></Sheet>
  </div>;
}
