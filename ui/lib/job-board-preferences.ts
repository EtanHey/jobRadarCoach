import { z } from "zod";
import type { ViewOptions } from "./job-filters";
import type { JobStatus } from "./job-status";

export const BOARD_PREFERENCES_KEY = "job-radar.board-preferences";
export const BOARD_PREFERENCES_VERSION = 1;

export type BoardFilter = "all" | "new-for-me" | JobStatus;
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
    sort: "fit",
  },
};

const storedPreferencesSchema = z.object({
  version: z.literal(BOARD_PREFERENCES_VERSION),
  filter: z.enum([
    "all", "new-for-me", "seen", "worth_checking", "applied", "screen",
    "interview_technical", "interview_final", "offer", "contract", "rejected",
    "archived", "not_relevant",
  ]),
  view: z.object({
    search: z.string().max(500),
    source: z.string().max(200),
    location: z.enum(["", "israel", "united-states", "other"]),
    seniority: z.enum(["", "non-senior", "Intern", "Junior", "Mid-level", "Senior", "Lead / Manager", "Staff / Principal", "Unknown"]),
    fit: z.enum(["", "recommended", "skip", "good", "scored", "unscored"]),
    sort: z.enum(["found", "posted", "fit", "seniority"]),
  }).strict(),
}).strict();

function freshDefaults(): BoardPreferences {
  return { ...DEFAULT_BOARD_PREFERENCES, view: { ...DEFAULT_BOARD_PREFERENCES.view } };
}

export function readBoardPreferences(storage: StorageReader): BoardPreferences {
  try {
    const raw = storage.getItem(BOARD_PREFERENCES_KEY);
    if (!raw) return freshDefaults();
    const parsed = storedPreferencesSchema.safeParse(JSON.parse(raw));
    return parsed.success ? { filter: parsed.data.filter, view: parsed.data.view } : freshDefaults();
  } catch {
    return freshDefaults();
  }
}

export function boardPreferenceStorage(host: StorageHost): Storage | null {
  try { return host.localStorage; } catch { return null; }
}

export function isDefaultBoardPreferences(preferences: BoardPreferences): boolean {
  return preferences.filter === DEFAULT_BOARD_PREFERENCES.filter
    && Object.entries(DEFAULT_BOARD_PREFERENCES.view).every(
      ([key, value]) => preferences.view[key as keyof ViewOptions] === value,
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
