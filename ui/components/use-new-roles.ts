"use client";
import { queryOptions, useQuery, useQueryClient } from "@tanstack/react-query";
import { JobListResponseSchema, type Availability, type JobSummary } from "@/lib/contracts";
import { NEW_ROLES_LIMIT, NEW_ROLES_MIN_GAP_MS, NEW_ROLES_POLL_MS, newRolesRequestPath } from "@/lib/new-roles";

type NewRoles = { jobs: JobSummary[]; truncated: boolean };
const NONE: NewRoles = { jobs: [], truncated: false };

export function newRolesQueryOptions(path: string) {
  return queryOptions({
    queryKey: ["new-roles", path], initialData: NONE, initialDataUpdatedAt: Date.now,
    gcTime: 0, staleTime: NEW_ROLES_MIN_GAP_MS, refetchOnMount: false,
    refetchInterval: NEW_ROLES_POLL_MS, refetchIntervalInBackground: false,
    refetchOnWindowFocus: query => Date.now() - Math.max(query.state.dataUpdatedAt, query.state.errorUpdatedAt) >= NEW_ROLES_MIN_GAP_MS,
    queryFn: async ({ signal }): Promise<NewRoles> => {
      const response = await fetch(path, { cache: "no-store", signal });
      if (!response.ok) throw new Error("New roles unavailable");
      const jobs = JobListResponseSchema.parse(await response.json()).jobs;
      return { jobs: jobs.slice(0, NEW_ROLES_LIMIT), truncated: jobs.length > NEW_ROLES_LIMIT };
    },
  });
}

// Reads a bounded page of postings newer than the loaded list; never touches the list itself.
export function useNewRoles(enabled: boolean, filter: string, availability: Availability, since: string) {
  const client = useQueryClient();
  const options = newRolesQueryOptions(newRolesRequestPath({ filter, availability, since }));
  const query = useQuery({ ...options, enabled });
  return { ...(enabled ? query.data : NONE), dismiss: () => client.setQueryData(options.queryKey, NONE) };
}
