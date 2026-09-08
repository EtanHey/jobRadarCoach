import assert from "node:assert/strict";
import { test } from "node:test";
import { experiencePhrase, postingUrl, titleSeniority } from "../lib/job-metadata";

test("Workable export URLs become a human page without changing other hosts", () => {
  assert.equal(postingUrl("https://apply.workable.com/example/jobs/view/ABC123.md"), "https://apply.workable.com/example/j/ABC123/");
  assert.equal(postingUrl("https://apply.workable.com/example/j/ABC123/apply"), "https://apply.workable.com/example/j/ABC123/apply");
  assert.equal(postingUrl("https://example.test/example/jobs/view/ABC123.md"), "https://example.test/example/jobs/view/ABC123.md");
});

test("seniority is explicit title evidence; unspecified titles stay unknown", () => {
  assert.equal(titleSeniority("Senior Backend Engineer"), "Senior");
  assert.equal(titleSeniority("Junior Fullstack Engineer"), "Junior");
  assert.equal(titleSeniority("Software Engineer"), null);
  assert.equal(titleSeniority("Staff Engineer"), "Staff / Principal");
});

test("experience quotes requirements and does not turn company age into experience", () => {
  assert.equal(experiencePhrase("Founded 20 years ago. You need 3+ years of experience in TypeScript."), "3+ years of experience");
  assert.equal(experiencePhrase("5–7 years professional experience"), "5–7 years professional experience");
  assert.equal(experiencePhrase("Our company is 25 years old."), null);
  assert.equal(experiencePhrase(null), null);
});
