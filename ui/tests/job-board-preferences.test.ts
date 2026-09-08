import assert from "node:assert/strict";
import { test } from "node:test";
import {
  BOARD_PREFERENCES_KEY,
  boardPreferenceStorage,
  clearBoardPreferences,
  defaultBoardPreferences,
  preferencesForBoardFilter,
  preferencesForPipelineStatuses,
  readBoardPreferences,
  writeBoardPreferences,
  type BoardPreferences,
} from "../lib/job-board-preferences";

function memoryStorage(initial: Record<string, string> = {}) {
  const values = new Map(Object.entries(initial));
  return {
    getItem(key: string) { return values.get(key) ?? null; },
    setItem(key: string, value: string) { values.set(key, value); },
    removeItem(key: string) { values.delete(key); },
    value(key: string) { return values.get(key) ?? null; },
  };
}

test("Israel, All roles, facets, sort, and search restore in a fresh tab", () => {
  const storage = memoryStorage();
  const selected = {
    filter: "all" as const,
    view: {
      search: "platform",
      source: "workable",
      location: "israel" as const,
      seniority: "Junior",
      fit: "recommended",
      statuses: ["worth_checking", "interview_technical"],
      sort: "posted" as const,
    },
  } satisfies BoardPreferences;

  writeBoardPreferences(storage, selected);
  const freshTab = { getItem: storage.getItem };

  assert.deepEqual(readBoardPreferences(freshTab), selected);
});

test("invalid, stale, and unavailable storage safely restore visible defaults", () => {
  const defaults = defaultBoardPreferences();
  for (const stored of [
    "not json",
    JSON.stringify({ version: 0, filter: "all", view: defaults.view }),
    JSON.stringify({ version: 2, filter: "all", view: { ...defaults.view, location: "hidden-place" } }),
    JSON.stringify({ version: 2, filter: "new", view: defaults.view }),
    JSON.stringify({ version: 2, filter: "all", view: { ...defaults.view, seniority: "hidden-level" } }),
  ]) {
    assert.deepEqual(readBoardPreferences(memoryStorage({ [BOARD_PREFERENCES_KEY]: stored })), defaults);
  }
  assert.deepEqual(readBoardPreferences({ getItem() { throw new Error("blocked"); } }), defaults);
});

test("a version-1 pipeline tab migrates to the equivalent visible status filter", () => {
  const legacy = {
    version: 1,
    filter: "interview_final",
    view: {
      search: "platform",
      source: "workable",
      location: "israel",
      seniority: "Junior",
      fit: "recommended",
      sort: "posted",
    },
  };

  assert.deepEqual(
    readBoardPreferences(memoryStorage({ [BOARD_PREFERENCES_KEY]: JSON.stringify(legacy) })),
    {
      filter: "all",
      view: { ...legacy.view, statuses: ["interview_final"] },
    },
  );
});

test("pipeline selections and cohort tabs transition without incompatible hidden state", () => {
  const selected = preferencesForPipelineStatuses(defaultBoardPreferences(), ["worth_checking", "offer"]);
  assert.equal(selected.filter, "all");
  assert.deepEqual(selected.view.statuses, ["worth_checking", "offer"]);

  const seen = preferencesForBoardFilter(selected, "seen");
  assert.equal(seen.filter, "seen");
  assert.deepEqual(seen.view.statuses, []);

  const selectedFromSeen = preferencesForPipelineStatuses(seen, ["applied"]);
  assert.equal(selectedFromSeen.filter, "all");
  assert.deepEqual(selectedFromSeen.view.statuses, ["applied"]);

  const fresh = preferencesForBoardFilter(selectedFromSeen, "new-for-me");
  assert.equal(fresh.filter, "new-for-me");
  assert.deepEqual(fresh.view.statuses, []);
});

test("a denied localStorage property getter cannot strand board hydration", () => {
  const denied = Object.defineProperty({}, "localStorage", {
    get() { throw new DOMException("Access denied", "SecurityError"); },
  });

  assert.equal(boardPreferenceStorage(denied as { readonly localStorage: Storage }), null);
});

test("reset removes stored state and defaults are not written back", () => {
  const storage = memoryStorage();
  writeBoardPreferences(storage, {
    filter: "all",
    view: { ...defaultBoardPreferences().view, statuses: ["offer"] },
  });
  assert.notEqual(storage.value(BOARD_PREFERENCES_KEY), null);

  clearBoardPreferences(storage);
  writeBoardPreferences(storage, defaultBoardPreferences());

  assert.equal(storage.value(BOARD_PREFERENCES_KEY), null);
});
