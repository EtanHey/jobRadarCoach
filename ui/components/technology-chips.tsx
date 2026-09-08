"use client";

import { useId, useState } from "react";

import { TechIcon } from "@/components/tech-icon";
import {
  technologyChipWindow,
  technologyKind,
  uniqueTechnologyNames,
} from "@/lib/technology-icons";

export function TechnologyChips({ names, limit = 4 }: {
  names: readonly string[];
  limit?: number;
}) {
  const listId = useId();
  const allNames = uniqueTechnologyNames(names);
  const signature = `${limit}\u0000${allNames.join("\u0000")}`;
  const [expandedFor, setExpandedFor] = useState<string | null>(null);
  const expanded = expandedFor === signature;
  const { visibleNames, hiddenCount, collapsedLimit } = technologyChipWindow(
    allNames, limit, expanded,
  );
  if (!allNames.length) return null;

  return <div
    id={listId}
    role="group"
    aria-label="Technologies"
    className="flex min-w-0 max-w-full flex-wrap items-center gap-1.5"
  >
    {visibleNames.map((name) => {
      const kind = technologyKind(name);
      return <span
        key={name.toLocaleLowerCase("en-US")}
        data-tech-kind={kind}
        title={name}
        className={`inline-flex max-w-full items-center gap-1.5 rounded-full border px-2 py-1 text-xs leading-tight ${
          kind === "concept"
            ? "border-dashed border-primary/30 bg-primary/5 text-foreground"
            : kind === "brand"
              ? "bg-muted/70 text-foreground"
              : "bg-card text-foreground"
        }`}
      >
        <TechIcon name={name} />
        <span className="min-w-0 whitespace-normal break-words text-left">{name}</span>
      </span>;
    })}
    {hiddenCount > 0 ? <button
      type="button"
      aria-controls={listId}
      aria-expanded="false"
      aria-label={`Show ${hiddenCount} more technologies`}
      title={`Show ${hiddenCount} more technologies`}
      className="rounded-full border bg-background px-2 py-1 text-xs text-muted-foreground hover:text-foreground focus-visible:outline-2 focus-visible:outline-offset-2"
      onClick={(event) => {
        event.stopPropagation();
        setExpandedFor(signature);
      }}
    >+{hiddenCount}</button> : null}
    {expanded && allNames.length > collapsedLimit ? <button
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
