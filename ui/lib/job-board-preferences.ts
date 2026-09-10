import { z } from "zod";
import type { ViewOptions } from "./job-filters";
import { pipelineStatusValues, type PipelineStatus } from "./job-status";

export const BOARD_PREFERENCES_KEY = "job-radar.board-preferences";
export const BOARD_PREFERENCES_VERSION = 3;

export type BoardFilter = "all" | "new-for-me" | "seen";
export type BoardPreferences = { filter: BoardFilter; view: ViewOptions };
type StorageReader = Pick<Storage, "getItem">;
type StorageWriter = Pick<Storage, "setItem" | "removeItem">;
type StorageHost = { readonly localStorage: Storage };

export const DEFAULT_BOARD_PREFERENCES: BoardPreferences = {
  filter: "new-for-me",
  view: {
    search: "",
    source: "",
    location: "",
    seniority: "",
    fit: "recommended",
    statuses: [],
    availability: "active",
    sort: "fit",
  },
};

const viewSchema = z.object({
  search: z.string().max(500),
  source: z.string().max(200),
  location: z.enum(["", "israel", "united-states", "other"]),
  seniority: z.enum(["", "non-senior", "Intern", "Junior", "Mid-level", "Senior", "Lead / Manager", "Staff / Principal", "Unknown"]),
  fit: z.enum(["", "recommended", "skip", "good", "scored", "unscored"]),
  sort: z.enum(["found", "posted", "fit", "seniority"]),
}).strict();
const pipelineStatusSchema = z.enum(pipelineStatusValues);
const availabilitySchema = z.enum(["active", "inactive", "all"]);
const storedPreferencesSchema = z.object({
  version: z.literal(BOARD_PREFERENCES_VERSION),
  filter: z.enum(["all", "new-for-me", "seen"]),
  view: viewSchema.extend({ statuses: z.array(pipelineStatusSchema).max(pipelineStatusValues.length), availability: availabilitySchema }).strict(),
}).strict();
const versionTwoPreferencesSchema = z.object({
  version: z.literal(2),
  filter: z.enum(["all", "new-for-me", "seen"]),
  view: viewSchema.extend({ statuses: z.array(pipelineStatusSchema).max(pipelineStatusValues.length) }).strict(),
}).strict();
const legacyPreferencesSchema = z.object({
  version: z.literal(1),
  filter: z.enum(["all", "new-for-me", "seen", ...pipelineStatusValues]),
  view: viewSchema,
}).strict();

function freshDefaults(): BoardPreferences {
  return { ...DEFAULT_BOARD_PREFERENCES, view: { ...DEFAULT_BOARD_PREFERENCES.view, statuses: [] } };
}

export function readBoardPreferences(storage: StorageReader): BoardPreferences {
  try {
    const raw = storage.getItem(BOARD_PREFERENCES_KEY);
    if (!raw) return freshDefaults();
    const json: unknown = JSON.parse(raw);
    const parsed = storedPreferencesSchema.safeParse(json);
    if (parsed.success) return { filter: parsed.data.filter, view: { ...parsed.data.view, statuses: [...new Set(parsed.data.view.statuses)] } };
    const versionTwo = versionTwoPreferencesSchema.safeParse(json);
    if (versionTwo.success) return { filter: versionTwo.data.filter, view: { ...versionTwo.data.view, statuses: [...new Set(versionTwo.data.view.statuses)], availability: "active" } };
    const legacy = legacyPreferencesSchema.safeParse(json);
    if (!legacy.success) return freshDefaults();
    const status = pipelineStatusValues.includes(legacy.data.filter as PipelineStatus)
      ? legacy.data.filter as PipelineStatus
      : null;
    return {
      filter: status ? "all" : legacy.data.filter as BoardFilter,
      view: { ...legacy.data.view, statuses: status ? [status] : [], availability: "active" },
    };
  } catch {
    return freshDefaults();
  }
}

export function boardPreferenceStorage(host: StorageHost): Storage | null {
  try { return host.localStorage; } catch { return null; }
}

export function isDefaultBoardPreferences(preferences: BoardPreferences): boolean {
  return preferences.filter === DEFAULT_BOARD_PREFERENCES.filter
    && preferences.view.statuses.length === 0
    && Object.entries(DEFAULT_BOARD_PREFERENCES.view).every(
      ([key, value]) => key === "statuses" || preferences.view[key as keyof ViewOptions] === value,
    );
}

export function writeBoardPreferences(storage: StorageWriter, preferences: BoardPreferences): void {
  try {
    if (isDefaultBoardPreferences(preferences)) {
      storage.removeItem(BOARD_PREFERENCES_KEY);
      return;
    }
    storage.setItem(BOARD_PREFERENCES_KEY, JSON.stringify({
      version: BOARD_PREFERENCES_VERSION,
      ...preferences,
    }));
  } catch {
    // Storage can be unavailable in privacy modes; the board remains usable in memory.
  }
}

export function clearBoardPreferences(storage: StorageWriter): void {
  try { storage.removeItem(BOARD_PREFERENCES_KEY); } catch {}
}

export function defaultBoardPreferences(): BoardPreferences {
  return freshDefaults();
}

export function preferencesForBoardFilter(preferences: BoardPreferences, filter: BoardFilter): BoardPreferences {
  return {
    filter,
    view: {
      ...preferences.view,
      fit: filter === "new-for-me" ? "recommended" : "",
      statuses: filter === "all" ? preferences.view.statuses : [],
    },
  };
}

export function preferencesForPipelineStatuses(preferences: BoardPreferences, statuses: PipelineStatus[]): BoardPreferences {
  return {
    filter: statuses.length > 0 ? "all" : preferences.filter,
    view: { ...preferences.view, statuses },
  };
}
