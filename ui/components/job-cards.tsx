"use client";
import { useEffect, useMemo, useRef, type RefObject } from "react";
import { createPrefetchIntent } from "@/lib/detail-prefetch";
import { type DuplicateJobGroup } from "@/lib/job-dedup";
import { partitionGlobeGroups } from "@/lib/globe-viewport";
import { keptCardStatus } from "@/lib/job-status";
import { JobCard } from "./job-card";
import { TechnologyChips } from "./technology-chips";
import { Button } from "./ui/button";

type Props = { groups: DuplicateJobGroup[]; globeOpen: boolean; filter?: string; visiblePostingIds?: readonly string[]; selectedId?: string | null;
  bubble?: { ids: string[]; place: string } | null; clearBubble?: () => void; onWholeWorld?: () => void;
  openerRef: RefObject<HTMLButtonElement | null>; selectJob: (id: string | null) => void; openDetail?: (id: string) => void; prefetchDetail?: (id: string) => void };
export function JobCards({ groups, globeOpen, filter = "", visiblePostingIds, selectedId, openerRef, selectJob, openDetail, prefetchDetail, bubble, clearBubble, onWholeWorld }: Props) {
  const prefetchIntent = useMemo(() => prefetchDetail && createPrefetchIntent(prefetchDetail), [prefetchDetail]);
  useEffect(() => () => prefetchIntent?.dispose(), [prefetchIntent]);
  const hoveredCard = useRef<string | null>(null);
  // Card hover tells the globe once per card boundary, never per mousemove.
  const hoverCard = (id: string | null) => { if (id !== hoveredCard.current) { hoveredCard.current = id; window.dispatchEvent(new CustomEvent("job-globe-hover", { detail: id })); } };
  const cardId = (target: EventTarget | null) => (target as Element | null)?.closest<HTMLElement>("[data-globe-card]")?.dataset.globeCard ?? null;
  const sections = useMemo(() => {
    if (!globeOpen || visiblePostingIds === undefined) return null;
    if (bubble) return { visible: groups.filter(group => bubble.ids.includes(group.job.id)), outside: [] };
    return partitionGlobeGroups(groups, visiblePostingIds);
  }, [groups, globeOpen, visiblePostingIds, bubble]);
  const cards = (rows: DuplicateJobGroup[]) => rows.map(({job, alternates}) => <div key={job.id} data-globe-card={job.id} data-globe-selected={selectedId === job.id || undefined}>
    <JobCard actions={globeOpen && selectedId === job.id ? <Button variant="outline" className="w-full" onClick={event => { openerRef.current = event.currentTarget; openDetail?.(job.id); }}>View job details</Button> : undefined}
      selected={globeOpen ? selectedId === job.id : undefined} keptStatus={keptCardStatus(filter, job.status)} logoSize={sections ? "sm" : "md"} job={job} alternateCount={alternates.length} openerRef={openerRef} selectJob={selectJob} prefetchIntent={prefetchIntent}>
      <TechnologyChips names={job.stack} presentation="card" />
    </JobCard>
  </div>);
  if (globeOpen && !sections) return <div role="status" className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground">Counting roles on screen…</div>;
  if (!sections) return <div className="grid grid-cols-1 gap-4 md:grid-cols-2 xl:grid-cols-3">{cards(groups)}</div>;
  // The header is a sibling above the list, so in the scrolling rail only the list scrolls and nothing paints behind the chip.
  return <div className="globe-rail-cards" onPointerOver={event => hoverCard(cardId(event.target))} onPointerLeave={() => hoverCard(null)}
    // Keyboard focus lights the globe dot exactly like hover; mouse and script focus leave that to the pointer.
    onFocus={event => { if ((event.target as Element).matches(":focus-visible")) hoverCard(cardId(event.target)); }} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget as Node | null)) hoverCard(null); }}>
    <div className="globe-rail-header flex items-center justify-between px-1"><h2 id="globe-visible-heading" className="text-sm font-semibold">{bubble ? <button type="button" onClick={clearBubble} aria-label={`Clear bubble filter: ${bubble.place} · ${sections.visible.length} ${sections.visible.length === 1 ? "role" : "roles"}`} className="rounded-full border border-primary px-3 py-1 text-primary">{bubble.place} · {sections.visible.length} {sections.visible.length === 1 ? "role" : "roles"} ×</button> : "On screen"}</h2>{!bubble && <span className="text-xs text-muted-foreground">{sections.visible.length} {sections.visible.length === 1 ? "role" : "roles"}</span>}</div>
    <div className="globe-rail-list space-y-5">
    <section data-globe-section="visible" aria-labelledby="globe-visible-heading">
      {sections.visible.length ? <div className="grid grid-cols-1 gap-3">{cards(sections.visible)}</div> : <div className="rounded-xl border border-dashed p-5 text-sm"><p className="font-medium">Nothing on screen here.</p><p className="mt-1 text-muted-foreground">Zoom out or drag to another region.</p><Button variant="outline" className="mt-4" onClick={onWholeWorld}>Show whole world</Button></div>}
    </section>
    {!bubble && <section data-globe-section="outside" aria-labelledby="globe-outside-heading">
      <div className="mb-3 flex items-center justify-between border-t px-1 pt-4"><h2 id="globe-outside-heading" className="text-sm font-semibold">Off screen</h2><span className="text-xs text-muted-foreground">{sections.outside.length} {sections.outside.length === 1 ? "role" : "roles"}</span></div>
      <p className="mb-3 px-1 text-xs text-muted-foreground">Other places, closed roles, and roles without a location.</p>
      <div className="grid grid-cols-1 gap-3">{cards(sections.outside)}</div>
    </section>}
    </div>
  </div>;
}
