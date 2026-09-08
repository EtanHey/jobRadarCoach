"use client";

import { Select } from "@base-ui/react/select";
import { Check, ChevronDown } from "lucide-react";

export type SelectOption = { value: string; label: string };

export function AppSelect({ label, value, options, onValueChange }: {
  label: string;
  value: string;
  options: readonly SelectOption[];
  onValueChange: (value: string) => void;
}) {
  return <Select.Root items={options} value={value} onValueChange={(next) => next !== null && onValueChange(next)}>
    <Select.Label className="cursor-default text-xs font-medium text-muted-foreground">{label}</Select.Label>
    <Select.Trigger className="mt-1.5 flex h-10 w-full min-w-0 items-center justify-between gap-2 rounded-lg border bg-background px-3 text-left text-sm text-foreground outline-none transition hover:bg-muted/60 focus-visible:ring-2 focus-visible:ring-ring data-popup-open:bg-muted/60">
      <Select.Value className="min-w-0 truncate" />
      <Select.Icon className="shrink-0 text-muted-foreground"><ChevronDown aria-hidden="true" size={15} /></Select.Icon>
    </Select.Trigger>
    <Select.Portal>
      <Select.Positioner align="start" alignItemWithTrigger={false} sideOffset={5} className="z-50 outline-none">
        <Select.Popup className="max-h-[min(20rem,var(--available-height))] min-w-[var(--anchor-width)] origin-[var(--transform-origin)] overflow-y-auto rounded-lg border bg-popover p-1 text-popover-foreground shadow-lg outline-none transition-[transform,opacity] duration-100 motion-reduce:transition-none data-ending-style:scale-95 data-ending-style:opacity-0 data-starting-style:scale-95 data-starting-style:opacity-0">
          <Select.List>
            {options.map((option) => <Select.Item key={option.value} value={option.value} className="grid cursor-default grid-cols-[1rem_minmax(0,1fr)] items-center gap-2 rounded-md px-2 py-2 text-sm outline-none data-highlighted:bg-accent data-highlighted:text-accent-foreground">
              <Select.ItemIndicator><Check aria-hidden="true" size={14} /></Select.ItemIndicator>
              <Select.ItemText className="col-start-2 truncate">{option.label}</Select.ItemText>
            </Select.Item>)}
          </Select.List>
        </Select.Popup>
      </Select.Positioner>
    </Select.Portal>
  </Select.Root>;
}
