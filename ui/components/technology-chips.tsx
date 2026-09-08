"use client";

import { useId, useState } from "react";

import { TechIcon } from "@/components/tech-icon";
import {
  technologyChipWindow,
  technologyKind,
  uniqueTechnologyNames,
} from "@/lib/technology-icons";

export function TechnologyChips({ names, limit = 4, presentation = "flow" }: {
  names: readonly string[];
  limit?: number;
  presentation?: "flow" | "card";
}) {
  const listId = useId();
  const effectiveLimit = presentation === "card" ? Math.min(limit, 4) : limit;
  const allNames = uniqueTechnologyNames(names);
  const signature = `${effectiveLimit}\u0000${allNames.join("\u0000")}`;
  const [expandedFor, setExpandedFor] = useState<string | null>(null);
  const expanded = expandedFor === signature;
  const { visibleNames, hiddenCount, collapsedLimit } = technologyChipWindow(
    allNames, effectiveLimit, expanded,
  );
  const compact = presentation === "card" && !expanded;
  if (!allNames.length) return null;

  return <div
    id={listId}
    role="group"
    aria-label="Technologies"
    className={compact ? "grid min-w-0 max-w-full grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] grid-rows-[1.625rem_1.625rem] gap-1.5" : "flex min-w-0 max-w-full flex-wrap items-center gap-1.5"}
  >
    {visibleNames.map((name, index) => {
      const kind = technologyKind(name);
      return <span
        key={name.toLocaleLowerCase("en-US")}
        data-tech-kind={kind}
        title={name}
        style={compact ? { gridColumn: index % 2 + 1, gridRow: Math.floor(index / 2) + 1 } : undefined}
        className={`inline-flex min-w-0 max-w-full items-center gap-1.5 rounded-full border px-2 py-1 text-xs leading-tight ${
          kind === "concept"
            ? "border-dashed border-primary/30 bg-primary/5 text-foreground"
            : kind === "brand"
              ? "bg-muted/70 text-foreground"
              : "bg-card text-foreground"
        }`}
      >
        <TechIcon name={name} />
        <span className={compact ? "min-w-0 truncate text-left" : "min-w-0 whitespace-normal break-words text-left"}>{name}</span>
      </span>;
    })}
    {hiddenCount > 0 || compact ? <button
      type="button"
      aria-controls={listId}
      aria-expanded="false"
      aria-label={hiddenCount ? `Show ${hiddenCount} more technologies` : "Expand full technology labels"}
      title={hiddenCount ? `Show ${hiddenCount} more technologies` : "Expand full technology labels"}
      style={compact ? { gridColumn: 3, gridRow: "1 / span 2", alignSelf: "center" } : undefined}
      className="rounded-full border bg-background px-2 py-1 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2"
      onClick={(event) => {
        event.stopPropagation();
        setExpandedFor(signature);
      }}
    >{hiddenCount ? `+${hiddenCount}` : "All"}</button> : null}
    {expanded && (allNames.length > collapsedLimit || presentation === "card") ? <button
      type="button"
      aria-controls={listId}
      aria-expanded="true"
      className="rounded-full px-2 py-1 text-xs text-muted-foreground underline-offset-2 hover:text-foreground hover:underline focus-visible:outline-2 focus-visible:outline-offset-2"
      onClick={(event) => {
        event.stopPropagation();
        setExpandedFor(null);
      }}
    >Show less</button> : null}
  </div>;
}
