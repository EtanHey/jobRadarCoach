import assert from "node:assert/strict";
import { test } from "node:test";
import { ScorePayloadSchema, ScoreReasonSchema } from "../lib/contracts";

const explanation =
  "First paragraph preserves the agent's complete explanation, including עברית and 🚀.\n\n" +
  "Second paragraph deliberately exceeds two hundred characters so a stored scoring reason can " +
  "reach the UI contract without truncation, whitespace normalization, or loss of its final " +
  "directional mark: \u202c";

test("scoring explanation contracts preserve long Unicode multiline text verbatim", () => {
  assert(explanation.length > 200);
  const reason = {
    factor: "product_role_match" as const,
    basis: "comparison" as const,
    assessment: "positive" as const,
    evidence_ids: ["posting:example", "example-project"],
    detail: explanation,
  };
  const payload = {
    employer_type: "direct" as const,
    seniority_real: true,
    fit_score: 82,
    fit_tier: "strong" as const,
    recommendation: "apply" as const,
    reasons: [reason],
    fit_line: explanation,
    fit_line_evidence_ids: ["posting:example", "example-project"],
    luna_status: "ok" as const,
  };

  assert.equal(ScoreReasonSchema.parse(reason).detail, explanation);
  const parsed = ScorePayloadSchema.parse(payload);
  assert.equal(parsed.reasons[0].detail, explanation);
  assert.equal(parsed.fit_line, explanation);
});
