import assert from "node:assert/strict";
import { test } from "node:test";
import { matchesFit } from "../lib/job-fit";

test("recommendations include reviewable stretch roles without claiming unscored jobs are relevant", () => {
  assert.equal(matchesFit({score: 44, recommendation: "review"}, "recommended"), true);
  assert.equal(matchesFit({score: 80, recommendation: "skip"}, "recommended"), false);
  assert.equal(matchesFit({score: null, recommendation: null}, "recommended"), false);
  assert.equal(matchesFit({score: null, recommendation: null}, ""), true);
});

test("skip, fit threshold and analysis status remain separate choices", () => {
  assert.equal(matchesFit({score: 0, recommendation: "skip"}, "skip"), true);
  assert.equal(matchesFit({score: 0, recommendation: "skip"}, "scored"), true);
  assert.equal(matchesFit({score: null, recommendation: null}, "unscored"), true);
  assert.equal(matchesFit({score: 44, recommendation: "review"}, "good"), false);
  assert.equal(matchesFit({score: 60, recommendation: "apply"}, "good"), true);
});
