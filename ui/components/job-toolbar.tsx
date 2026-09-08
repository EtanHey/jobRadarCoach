"use client";
import type { JobSummary } from "@/lib/contracts";
import { levelOrder, type ViewOptions } from "@/lib/job-filters";

export function JobToolbar({ jobs, options, onChange }: {
  jobs: JobSummary[]; options: ViewOptions; onChange: (next: ViewOptions) => void;
}) {
  const fields = [
    { key: "source", label: "Source", choices: [["", "All sources"], ...[...new Set([...jobs.map((job) => job.source), ...(options.source ? [options.source] : [])])].sort().map((source) => [source, source])] },
    { key: "seniority", label: "Seniority", choices: [["", "All levels"], ["non-senior", "Hide senior+ (keep unknown)"], ...levelOrder.map((level) => [level, level])] },
    { key: "fit", label: "Fit", choices: [["", "Any fit"], ["good", "60+ fit score"], ["scored", "Scored"], ["unscored", "Not scored"]] },
    { key: "sort", label: "Sort", choices: [["found", "Recently found"], ["posted", "Recently posted"], ["fit", "Best fit first"], ["seniority", "Seniority: junior first"]] },
  ] as const;
  return <div className="grid grid-cols-2 items-end gap-3 border-b py-5 md:grid-cols-4">
    {fields.map(({key, label, choices}) => <label key={key} className="flex min-w-0 flex-col gap-1.5 text-xs font-medium text-muted-foreground">{label}
      <select aria-label={label} value={options[key]} onChange={(event) => onChange({ ...options, [key]: event.target.value })} className="min-w-0 w-full rounded-lg border bg-background px-3 py-2 text-sm text-foreground">
        {choices.map(([value, text]) => <option key={value} value={value}>{text}</option>)}
      </select>
    </label>)}
    <p className="col-span-full text-xs text-muted-foreground">{jobs.filter((job) => job.score !== null).length} of {jobs.length} loaded roles scored. Unscored roles stay visible; analysis runs separately.</p>
  </div>;
}
