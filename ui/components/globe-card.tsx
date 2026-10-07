"use client";
import { useEffect, useRef, useState, type ComponentProps } from "react";
import { useQuery } from "@tanstack/react-query";
import { JobListResponseSchema, type JobSummary } from "@/lib/contracts";
import type { GlobeJob } from "@/lib/globe-contract";
import { JobCard } from "./job-card";
export function GlobeCard({job, ...props}: Omit<ComponentProps<typeof JobCard>, "job"> & {job: GlobeJob}) {
  const root = useRef<HTMLDivElement | null>(null);
  const [visible, setVisible] = useState(false);
  useEffect(() => {
    const observer = new IntersectionObserver(entries => {
      if (entries.some(entry => entry.isIntersecting)) { setVisible(true); observer.disconnect(); }
    }, {rootMargin: "300px"});
    if (root.current) observer.observe(root.current);
    return () => observer.disconnect();
  }, []);
  const query = useQuery({
    queryKey: ["globe-card",job.id], enabled: visible,
    queryFn: async ({signal}) => {
      const params = new URLSearchParams({filter:"all",availability:"all",limit:"1",ids:job.id});
      const response = await fetch("/api/jobs?" + params, {cache:"no-store",signal});
      if (!response.ok) throw new Error("Role unavailable");
      const row = JobListResponseSchema.parse(await response.json()).jobs.find(row => row.id === job.id);
      if (!row) throw new Error("Role unavailable");
      return row;
    },
  });
  return <div ref={root}>{query.data
    ? <JobCard {...props} job={{...query.data,...job}} />
    : <div className="min-h-64 rounded-xl border bg-card p-4" role="status"><p>{job.company}</p><p className="mt-1 font-semibold">{job.title}</p><p className="mt-4 text-xs text-muted-foreground">{query.error ? "Could not load role." : "Loading role…"}{query.error && <button className="ml-2 underline" onClick={() => void query.refetch()}>Retry</button>}</p></div>}</div>;
}
// Full list rows render immediately; marker-only rows hydrate when they approach the rail.
function isCardSummary(job: GlobeJob): job is JobSummary { return "experience" in job; }
export function BoardCard(props: Omit<ComponentProps<typeof JobCard>, "job"> & {job: GlobeJob}) {
  return isCardSummary(props.job) ? <JobCard {...props} job={props.job} /> : <GlobeCard {...props} />;
}
