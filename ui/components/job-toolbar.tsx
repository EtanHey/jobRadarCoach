"use client";
import type { JobSummary } from "@/lib/contracts";
import { levelOrder, type ViewOptions } from "@/lib/job-filters";
import { AppSelect, type SelectOption } from "@/components/ui/select";

export function JobToolbar({ jobs, options, onChange }: {
  jobs: JobSummary[]; options: ViewOptions; onChange: (next: ViewOptions) => void;
}) {
  const fields: { key: keyof ViewOptions; label: string; choices: SelectOption[] }[] = [
    { key: "source", label: "Source", choices: [{value: "", label: "All sources"}, ...[...new Set([...jobs.map((job) => job.source), ...(options.source ? [options.source] : [])])].sort().map((source) => ({value: source, label: source}))] },
    { key: "location", label: "Location", choices: [{value: "", label: "All locations"}, {value: "israel", label: "Israel"}, {value: "united-states", label: "United States"}, {value: "other", label: "Other"}] },
    { key: "seniority", label: "Seniority", choices: [{value: "", label: "All levels"}, {value: "non-senior", label: "Hide senior+ (keep unknown)"}, ...levelOrder.map((level) => ({value: level, label: level}))] },
    { key: "fit", label: "Fit", choices: [{value: "", label: "Any fit"}, {value: "recommended", label: "Worth considering"}, {value: "skip", label: "Suggested skip"}, {value: "good", label: "60+ fit score"}, {value: "scored", label: "Scored"}, {value: "unscored", label: "Not scored"}] },
    { key: "sort", label: "Sort", choices: [{value: "found", label: "Recently found"}, {value: "posted", label: "Recently posted"}, {value: "fit", label: "Best fit first"}, {value: "seniority", label: "Seniority: junior first"}] },
  ] as const;
  return <div className="grid grid-cols-2 items-end gap-3 border-b py-5 md:grid-cols-3 xl:grid-cols-5">
    {fields.map(({key, label, choices}) => <div key={key} className="min-w-0"><AppSelect label={label} value={options[key]} options={choices} onValueChange={(value) => onChange({ ...options, [key]: value })} /></div>)}
    <p className="col-span-full text-xs text-muted-foreground">{jobs.filter((job) => job.score !== null).length} of {jobs.length} loaded roles scored. {options.fit === "recommended" ? "Showing roles recommended to apply, seek a referral, or review. Choose Any fit to include unscored roles and suggested skips." : "Choose Worth considering to focus on roles recommended to apply, seek a referral, or review."}</p>
  </div>;
}
