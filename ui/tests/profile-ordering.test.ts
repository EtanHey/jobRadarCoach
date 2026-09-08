import assert from "node:assert/strict";
import { test } from "node:test";

import { makePatchProfile } from "../app/api/profile/route";
import type { Profile, ProfileEntry } from "../lib/contracts";
import { moveProfileItem } from "../lib/profile-ordering";
import type { ApiStore } from "../lib/server";

const profile: Profile = {
  "candidate.roles_wanted": ["Product Engineer", "Frontend Engineer"],
  "candidate.stacks": ["React", "TypeScript", "Next.js", "Svelte"],
  "candidate.seniority": ["Senior"],
  "candidate.open_to.geographies": ["Israel"],
  "candidate.remote": null,
  "candidate.salary_floor": null,
  "candidate.red_flag_words": [],
  "candidate.preferences.free_text": null,
  "runtime.brain": "codex",
};

test("profile priorities can move earlier without sorting the other entries", () => {
  assert.deepEqual(
    moveProfileItem(["React", "TypeScript", "Next.js", "Svelte"], 3, 1),
    ["React", "Svelte", "TypeScript", "Next.js"],
  );
});

test("profile priorities can move later without mutating the saved array", () => {
  const saved = ["React", "TypeScript", "Next.js", "Svelte"];
  assert.deepEqual(
    moveProfileItem(saved, 0, 2),
    ["TypeScript", "Next.js", "React", "Svelte"],
  );
  assert.deepEqual(saved, ["React", "TypeScript", "Next.js", "Svelte"]);
});

test("invalid and unchanged moves preserve the current order", () => {
  const values = ["Product Engineer", "Frontend Engineer"];
  assert.deepEqual(moveProfileItem(values, 0, 0), values);
  assert.deepEqual(moveProfileItem(values, -1, 0), values);
  assert.deepEqual(moveProfileItem(values, 0, 2), values);
});

test("profile PATCH forwards and reloads the chosen array order without a database write", async () => {
  let intercepted: ProfileEntry | undefined;
  const store = {
    updateProfile: async (input: ProfileEntry) => {
      intercepted = input;
      return { ...profile, [input.field]: input.value } as Profile;
    },
  } as ApiStore;
  const order = ["React", "Svelte", "TypeScript", "Next.js"];
  const request = new Request("http://localhost/api/profile", {
    method: "PATCH",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ field: "candidate.stacks", value: order }),
  });

  const response = await makePatchProfile(store)(request);

  assert.equal(response.status, 200);
  assert.deepEqual(intercepted, { field: "candidate.stacks", value: order });
  assert.deepEqual((await response.json()).profile["candidate.stacks"], order);
});
