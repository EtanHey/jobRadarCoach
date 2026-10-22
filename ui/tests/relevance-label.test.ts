import assert from "node:assert/strict";
import test from "node:test";
import { relevanceLabel } from "../lib/relevance-label";

test("JD quality reasons explain why automatic scoring is withheld", () => {
  for (const rule of ["missing-body", "unfilled-template", "mixed-role", "external-summary", "listing-only"]) {
    const slug = `jd-quality-${rule}`;
    const label = relevanceLabel(slug);
    assert.ok(label.startsWith("JD quality:"));
    assert.notEqual(label, slug);
  }
  assert.equal(relevanceLabel("future-rule"), "future-rule");
});
