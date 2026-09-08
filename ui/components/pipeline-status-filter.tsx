"use client";

import { useRef } from "react";
import { ChevronDown } from "lucide-react";
import { pipelineStatusOptions, type PipelineStatus } from "@/lib/job-status";
import { Button } from "./ui/button";

export function PipelineStatusFilter({ value, onChange }: {
  value: PipelineStatus[];
  onChange: (value: PipelineStatus[]) => void;
}) {
  const detailsRef = useRef<HTMLDetailsElement | null>(null);
  const labels = pipelineStatusOptions.filter((option) => value.includes(option.value)).map((option) => option.label);
  const selection = labels.length === 0 ? "All statuses" : labels.join(", ");
  function closeAndRestoreFocus() {
    const details = detailsRef.current;
    if (!details) return;
    details.open = false;
    details.querySelector("summary")?.focus();
  }
  return <div className="min-w-0">
    <span className="cursor-default text-xs font-medium text-muted-foreground">Pipeline status</span>
    <details
      ref={detailsRef}
      className="relative mt-1.5 min-w-0"
      onBlur={(event) => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false; }}
      onKeyDown={(event) => { if (event.key === "Escape" && event.currentTarget.open) { event.preventDefault(); event.stopPropagation(); closeAndRestoreFocus(); } }}
    >
      <summary aria-label={`Pipeline status: ${selection}${value.length > 0 ? `. ${value.length} selected` : ""}`} className="flex h-10 cursor-pointer list-none items-center justify-between gap-2 rounded-lg border bg-background px-3 text-left text-sm text-foreground outline-none transition hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring [&::-webkit-details-marker]:hidden">
        <span className="min-w-0 flex-1 truncate">{selection}</span>
        {value.length > 0 && <span className="shrink-0 rounded-full bg-primary px-1.5 text-xs text-primary-foreground">{value.length}<span className="sr-only"> selected</span></span>}
        <ChevronDown className="size-4 shrink-0 opacity-50" aria-hidden="true" />
      </summary>
      <div className="absolute bottom-full right-0 z-30 mb-1 w-[min(18rem,calc(100vw-2rem))] rounded-md border bg-popover p-3 text-popover-foreground shadow-md md:bottom-auto md:top-full md:mb-0 md:mt-1">
        <fieldset className="grid gap-2">
          <legend className="sr-only">Pipeline statuses</legend>
          {pipelineStatusOptions.map((option) => <label key={option.value} className="flex cursor-pointer items-center gap-2 rounded-sm px-1 py-1 text-sm hover:bg-muted">
            <input
              type="checkbox"
              checked={value.includes(option.value)}
              onChange={(event) => onChange(event.target.checked ? [...value, option.value] : value.filter((item) => item !== option.value))}
              className="size-4 accent-primary"
            />
            {option.label}
          </label>)}
        </fieldset>
        <div className="mt-3 flex justify-end border-t pt-2"><Button type="button" variant="ghost" size="sm" disabled={value.length === 0} onClick={() => onChange([])}>Clear</Button></div>
      </div>
    </details>
  </div>;
}
