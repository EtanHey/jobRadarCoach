"use client";

import { useRef, useState, type ComponentProps, type ReactNode } from "react";
import { Tooltip } from "@base-ui/react/tooltip";
import { cn } from "@/lib/utils";

type Props = Omit<ComponentProps<"button">, "children"> & { label: string; tip: string; children: ReactNode };

// A compact icon trigger whose full wording is its accessible name and a tooltip.
// Hover, keyboard focus and tap all open it (touch has no hover); tap again or Escape closes.
export function InfoTip({ label, tip, children, className, ...rest }: Props) {
  const [open, setOpen] = useState(false);
  const openAtPress = useRef<boolean | null>(null);
  // Opened by a press (tap or click), it stays put until a second press, blur or Escape: leaving hover must not close it.
  const pinned = useRef(false);
  const change = (next: boolean) => { if (!next) pinned.current = false; setOpen(next); };
  return <Tooltip.Root open={open} onOpenChange={(next, details) => { if (!next && pinned.current && details.reason === "trigger-hover") return; change(next); }}>
    <Tooltip.Trigger {...rest} type="button" aria-label={label} delay={150} closeOnClick={false}
      onPointerDown={() => { openAtPress.current = open; }}
      onFocus={() => setOpen(true)}
      onBlur={() => change(false)}
      onClick={() => { const next = !(openAtPress.current ?? open); openAtPress.current = null; pinned.current = next; change(next); }}
      className={cn("pointer-events-auto relative z-10 inline-flex cursor-help items-center gap-0.5 rounded-sm tabular-nums outline-none focus-visible:ring-2 focus-visible:ring-ring", className)}>
      {children}
    </Tooltip.Trigger>
    <Tooltip.Portal>
      <Tooltip.Positioner sideOffset={6} className="z-[60]">
        <Tooltip.Popup role="tooltip" className="rounded-md border bg-popover px-2 py-1 text-xs whitespace-nowrap text-popover-foreground shadow-md">{tip}</Tooltip.Popup>
      </Tooltip.Positioner>
    </Tooltip.Portal>
  </Tooltip.Root>;
}
