"use client";
import { useMemo, type RefObject } from "react";
import type { DuplicateJobGroup } from "@/lib/job-dedup";
import { partitionGlobeGroups } from "@/lib/globe-viewport";
import { JobCard } from "./job-card";
import { TechnologyChips } from "./technology-chips";
import { Button } from "./ui/button";

type Props = { groups: DuplicateJobGroup[]; globeOpen: boolean; visiblePostingIds?: readonly string[]; selectedId?: string | null;
  openerRef: RefObject<HTMLButtonElement | null>; selectJob: (id: string | null) => void; openDetail?: (id: string) => void };
export function JobCards({ groups, globeOpen, visiblePostingIds, selectedId, openerRef, selectJob, openDetail }: Props) {
  const sections = useMemo(() => globeOpen && visiblePostingIds !== undefined ? partitionGlobeGroups(groups, visiblePostingIds) : null, [groups, globeOpen, visiblePostingIds]);
  const cards = (rows: DuplicateJobGroup[]) => rows.map(({job, alternates}) => <div key={job.id} data-globe-selected={selectedId === job.id || undefined}>
    <JobCard actions={globeOpen && selectedId === job.id ? <Button variant="outline" className="w-full" onClick={event => { openerRef.current = event.currentTarget; openDetail?.(job.id); }}>View job details</Button> : undefined}
      selected={globeOpen ? selectedId === job.id : undefined} job={job} alternateCount={alternates.length} openerRef={openerRef} selectJob={selectJob}>
      <TechnologyChips names={job.stack} presentation="card" />
    </JobCard>
  </div>);
  if (globeOpen && !sections) return <div role="status" className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">Loading globe positions and view…</div>;
  if (!sections) return <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">{cards(groups)}</div>;
  return <div className="space-y-5">
    <section data-globe-section="visible" aria-labelledby="globe-visible-heading">
      <div className="mb-3 flex items-center justify-between px-1"><h2 id="globe-visible-heading" className="text-sm font-semibold">On screen</h2><span className="text-xs text-muted-foreground">{sections.visible.length} {sections.visible.length === 1 ? "role" : "roles"}</span></div>
      {sections.visible.length ? <div className="grid grid-cols-1 gap-3">{cards(sections.visible)}</div> : <p className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">No roles in this part of the globe. Pan or zoom to explore.</p>}
    </section>
    <section data-globe-section="outside" aria-labelledby="globe-outside-heading">
      <div className="mb-3 flex items-center justify-between border-t px-1 pt-4"><h2 id="globe-outside-heading" className="text-sm font-semibold">Outside of screen</h2><span className="text-xs text-muted-foreground">{sections.outside.length} {sections.outside.length === 1 ? "role" : "roles"}</span></div>
      <p className="mb-3 px-1 text-xs text-muted-foreground">Other locations, unavailable listings and roles without mapped locations.</p>
      <div className="grid grid-cols-1 gap-3">{cards(sections.outside)}</div>
    </section>
  </div>;
}
