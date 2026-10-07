import assert from "node:assert/strict";
import { test } from "node:test";
import { jobListRequestPath } from "../lib/job-board-state";
import { filterJobGroups } from "../lib/job-filters";
import type { JobSummary } from "../lib/contracts";
import {
  BOARD_PREFERENCES_KEY,
  boardPreferenceStorage,
  clearBoardPreferences,
  defaultBoardPreferences,
  preferencesForBoardFilter,
  preferencesForPipelineStatuses,
  readBoardPreferences,
  writeBoardPreferences,
  viewForBoardQuery,
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
      availability: "inactive" as const,
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
    JSON.stringify({ version: 3, filter: "all", view: { ...defaults.view, location: "hidden-place" } }),
    JSON.stringify({ version: 3, filter: "new", view: defaults.view }),
    JSON.stringify({ version: 3, filter: "all", view: { ...defaults.view, seniority: "hidden-level" } }),
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
      view: { ...legacy.view, statuses: ["interview_final"], availability: "active" },
    },
  );
});

test("version-2 preferences migrate to the safe active availability default", () => {
  const previous = {
    version: 2,
    filter: "all",
    view: {
      search: "platform", source: "", location: "israel", seniority: "",
      fit: "", statuses: ["offer"], sort: "found",
    },
  };
  assert.deepEqual(
    readBoardPreferences(memoryStorage({ [BOARD_PREFERENCES_KEY]: JSON.stringify(previous) })),
    { filter: "all", view: { ...previous.view, availability: "active" } },
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

test("remote and non-remote filters survive reload without changing old defaults", () => {
  for (const remote of [true, false]) {
    const storage = memoryStorage();
    const preferences = defaultBoardPreferences();
    preferences.view.remote = remote;
    writeBoardPreferences(storage, preferences);
    assert.equal(readBoardPreferences(storage).view.remote, remote);
  }
});

test("collapsed filters persist with otherwise default preferences and survive tab changes", () => {
  const storage = memoryStorage();
  const collapsed = { ...defaultBoardPreferences(), filtersCollapsed: true };
  writeBoardPreferences(storage, collapsed);
  assert.equal(readBoardPreferences(storage).filtersCollapsed, true);
  const changed = preferencesForBoardFilter(readBoardPreferences(storage), "seen");
  assert.equal(changed.filtersCollapsed, true);
  assert.equal(preferencesForPipelineStatuses(changed, ["offer"]).filtersCollapsed, true);
  clearBoardPreferences(storage);
  assert.equal(readBoardPreferences(storage).filtersCollapsed ?? false, false);
});

test("leaving Not scored preserves availability and found-within before and after reload", () => {
  for (const availability of ["active", "inactive", "all"] as const) {
    for (const reloadInArchive of [false, true]) {
      const storage = memoryStorage();
      const prior: BoardPreferences = {
        filter: "all",
        view: { ...defaultBoardPreferences().view, availability, found_within: "7d" },
      };
      let archive = preferencesForBoardFilter(prior, "not-scored");
      writeBoardPreferences(storage, archive);
      if (reloadInArchive) archive = readBoardPreferences(storage);
      for (const filter of ["new-for-me", "all", "seen"] as const) {
        const returned = preferencesForBoardFilter(archive, filter);
        assert.equal(returned.view.availability, availability);
        assert.equal(returned.view.found_within, "7d");
        writeBoardPreferences(storage, returned);
        assert.deepEqual(readBoardPreferences(storage), returned);
      }
    }
  }
});

test("archive query includes older and inactive roles without persisting its overrides", () => {
  const storage = memoryStorage();
  const prior: BoardPreferences = {
    filter: "all", view: { ...defaultBoardPreferences().view, found_within: "24h" },
  };
  const archive = preferencesForBoardFilter(prior, "not-scored");
  const queryView = viewForBoardQuery(archive);
  assert.equal(queryView.availability, "all");
  assert.equal(queryView.found_within, "");
  const path = jobListRequestPath({ filter: archive.filter, ...queryView, limit: 1000 });
  assert.match(path, /availability=all/);
  assert.doesNotMatch(path, /found_within=/);
  const oldRole = { id: "old", title: "Engineer", company: "Synthetic", source: "fixture",
    first_seen_at: "2000-01-01T00:00:00Z", location: null, seniority: null, stack: [],
    score: null, status: "new", relevance_filtered: true, alive: false } as unknown as JobSummary;
  assert.equal(filterJobGroups([oldRole], queryView).length, 1);
  assert.equal(filterJobGroups([oldRole], archive.view).length, 0);
  writeBoardPreferences(storage, archive);
  assert.deepEqual(readBoardPreferences(storage), archive);
  assert.equal(readBoardPreferences(storage).view.availability, "active");
  assert.equal(readBoardPreferences(storage).view.found_within, "24h");
  const returned = preferencesForBoardFilter(readBoardPreferences(storage), "new-for-me");
  assert.deepEqual(viewForBoardQuery(returned), returned.view);
});
