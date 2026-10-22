import assert from "node:assert/strict";
import { test } from "node:test";
import { isValidElement, type ReactNode } from "react";
import { AssessmentSheet } from "../../components/assessment-sheet";
import { JobDetailSchema } from "../../lib/contracts";
import { matchesFit } from "../../lib/job-fit";

function text(node: ReactNode): string {
  if (typeof node === "string" || typeof node === "number") return String(node);
  if (Array.isArray(node)) return node.map(text).join("");
  if (isValidElement<{ children?: ReactNode }>(node)) return text(node.props.children);
  return "";
}
const base = {
  id: "00000000-0000-0000-0000-000000000001", title: "Engineer", company: "Example",
  source: "fixture", last_seen_at: "2026-10-22", experience: null, location: "Remote",
  remote: true, seniority: null, stack: [], url: "https://example.test/job", apply_url: null,
  posted_at: null, first_seen_at: "2026-10-22", status: "new", status_reason: null,
  score: 90, fit_line: "Strong skill fit", recommendation: "apply", salary: null,
  description_available: true, seniority_origin: "unknown", extraction_state: "extracted",
  raw_jd: "Remote U.S. only", reasons: [], score_payload: null, brain: "fixture", scored_at: null,
};
for (const [eligibility, expected] of [
  ["blocked", 'Apply — location blocked: "Remote U.S. only"'],
  ["unknown", 'Apply — location unknown: check "Remote U.S. only"'],
  ["eligible", "Recommendation: apply"],
  [undefined, "Apply — location unknown: check location eligibility has not been assessed"],
] as const) {
  test(`AssessmentSheet qualifies ${eligibility ?? "legacy"} apply advice`, () => {
    const job = JobDetailSchema.parse({ ...base, eligibility, eligibility_reason: eligibility ? '"Remote U.S. only"' : undefined });
    assert.ok(text(AssessmentSheet({ job })).includes(expected));
  });
}

test("previous archived assessment keeps its eligibility qualification", () => {
  const job = JobDetailSchema.parse({ ...base, score: null, recommendation: null,
    relevance_filtered: true, score_payload: {
      employer_type: "direct", seniority_real: false, fit_score: 90, fit_tier: "strong",
      recommendation: "apply", reasons: [], fit_line: "Strong skill fit",
      fit_line_evidence_ids: [], luna_status: "ok", eligibility: "blocked",
      eligibility_reason: '"Remote U.S. only"',
    } });
  const rendered = text(AssessmentSheet({ job }));
  assert.ok(rendered.includes("Previous AI assessment"));
  assert.ok(rendered.includes('Apply — location blocked: "Remote U.S. only"'));
});

for (const previous of [false, true]) {
  for (const [eligibility_reason, expected] of [
    ['unresolved location restriction: "Must work EST hours"', 'Apply — location unclear: "Must work EST hours"'],
    ['Israel/remote-from-Israel scope is unconfirmed: "Remote"', "Recommendation: apply"],
  ]) {
    test(`${previous ? "archived" : "current"} unknown advice follows its reason prefix`, () => {
      const job = JobDetailSchema.parse({ ...base,
        ...(previous ? { score: null, recommendation: null, relevance_filtered: true,
          score_payload: { employer_type: "direct", seniority_real: false, fit_score: 90,
            fit_tier: "strong", recommendation: "apply", reasons: [], fit_line: "Strong skill fit",
            fit_line_evidence_ids: [], luna_status: "ok", eligibility: "unknown", eligibility_reason } }
          : { eligibility: "unknown", eligibility_reason }),
      });
      const rendered = text(AssessmentSheet({ job }));
      assert.ok(rendered.includes(expected));
      if (expected === "Recommendation: apply") assert.ok(!rendered.includes("location unclear") && !rendered.includes("location unknown"));
      const display = JobDetailSchema.parse({ ...base, eligibility: "unknown", eligibility_reason });
      assert.equal(matchesFit(display, "recommended"), true);
      assert.equal(matchesFit({ ...display, eligibility: "eligible" }, "recommended"), true);
      assert.equal(matchesFit({ ...display, eligibility: "blocked" }, "recommended"), false);
    });
  }
}
