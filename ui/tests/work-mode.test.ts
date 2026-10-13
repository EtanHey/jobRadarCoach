import assert from "node:assert/strict";
import { test } from "node:test";
import { readBoardPreferences, writeBoardPreferences, defaultBoardPreferences } from "../lib/job-board-preferences";

test("hybrid survives saved preferences", () => {
  let saved = "";
  const storage = { getItem: () => saved, setItem: (_key: string, value: string) => { saved = value; }, removeItem: () => { saved = ""; } };
  const preferences = defaultBoardPreferences();
  preferences.view.work_mode = "hybrid";
  writeBoardPreferences(storage, preferences);
  assert.equal(readBoardPreferences(storage).view.work_mode, "hybrid");
});
