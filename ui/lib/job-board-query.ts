import type { Availability, JobSummary } from "./contracts";
import type { BoardFilter } from "./job-board-preferences";

export type CachedList = { jobs: JobSummary[]; loadedUpdatedAt: string | null };
export const boardListKey = (filter: BoardFilter, availability: Availability) => ["board-list", filter, availability] as const;
