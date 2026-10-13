"use client";
import { queryOptions, useQuery, useQueryClient } from "@tanstack/react-query";
import { type Availability, type FoundWithin, type JobSummary } from "@/lib/contracts";
import { NEW_ROLES_MIN_GAP_MS, NEW_ROLES_POLL_MS, newRolesRequestPath } from "@/lib/new-roles";

import { NewRolesResponseSchema, NewRolesProbeSchema } from "@/lib/new-roles-contract";
import type { ViewOptions } from "@/lib/job-filters";
import { normalizedIdentity } from "@/lib/job-dedup";
import { defaultBoardPreferences } from "@/lib/job-board-preferences";
type NewRoles = { count: number; truncated: boolean };
const NONE: NewRoles = { count: 0, truncated: false };

export function newRolesQueryOptions(path: string, ids: string[] = [], view: ViewOptions = defaultBoardPreferences().view, loaded?: Pick<JobSummary,"id"|"company">[]) {
  return queryOptions({
    queryKey: ["new-roles", path, ids, view, loaded], initialData: NONE, initialDataUpdatedAt: Date.now,
    gcTime: 0, staleTime: NEW_ROLES_MIN_GAP_MS, refetchOnMount: false,
    refetchInterval: NEW_ROLES_POLL_MS, refetchIntervalInBackground: false,
    refetchOnWindowFocus: query => Date.now() - Math.max(query.state.dataUpdatedAt, query.state.errorUpdatedAt) >= NEW_ROLES_MIN_GAP_MS,
    queryFn: async ({ signal }): Promise<NewRoles> => {
      const probe = await fetch(path, {cache:"no-store",signal});
      if (!probe.ok) throw new Error("New roles unavailable");
      const arrivals = NewRolesProbeSchema.parse(await probe.json());
      if (!arrivals.count && !arrivals.truncated) return NONE;
      const companies=new Set(arrivals.companies);
      const relevantIds=loaded ? loaded.filter(job=>companies.has(normalizedIdentity(job.company))).map(job=>job.id) : ids;
      const params = Object.fromEntries(new URL(path, "http://localhost").searchParams);
      const response = await fetch(path.split("?")[0], { cache: "no-store", signal, method: "POST", headers: {"content-type":"application/json"}, body: JSON.stringify({...params, ids:relevantIds, view, incoming_ids: arrivals.incoming_ids}) });
      if (!response.ok) throw new Error("New roles unavailable");
      return NewRolesResponseSchema.parse(await response.json());
    },
  });
}

// Reads a count for the current view and loaded ids; never changes the list itself.
export function useNewRoles(enabled: boolean, filter: string, availability: Availability, since: string, found_within?: FoundWithin, jobs: JobSummary[] = [], view: ViewOptions = defaultBoardPreferences().view) {
  const client = useQueryClient();
  const options = newRolesQueryOptions(newRolesRequestPath({ filter, availability, since, found_within }), jobs.map(job => job.id), view, jobs.map(({id,company})=>({id,company})));
  const query = useQuery({ ...options, enabled });
  return { ...(enabled ? query.data : NONE), dismiss: () => client.setQueryData(options.queryKey, NONE) };
}
