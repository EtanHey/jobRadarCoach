import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import { employerLabel } from "../lib/employer-identity";

for (const [publisher, employer, expected] of [
  ["EngRadar", "Monday.com", "Monday.com via EngRadar"],
  ["Torentify", null, "Torentify (agency — client undisclosed)"],
  ["Wix", "Wix", "Wix"],
] as const) {
  test(`card renders employer identity: ${publisher}`, () => {
    const identity = { publisher, hiring_employer: employer, employer_evidence: employer ? `${employer} is hiring` : null, resolver_version: "1" };
    assert.equal(employerLabel({ company: publisher, employer_identity: identity }), expected);
    const probe = spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "--eval", `
      import React from "react";
      import { renderToStaticMarkup } from "react-dom/server";
      import { JobCard } from "./components/job-card.tsx";
      process.stdout.write(renderToStaticMarkup(React.createElement(JobCard, {
        job: {id:"00000000-0000-4000-8000-000000000001", title:"Engineer", company:${JSON.stringify(publisher)}, employer_identity:${JSON.stringify(identity)}, source:"linkedin", status:"new", score:null, stack:[], experience:null, location:null, url:"https://example.test", apply_url:null, posted_at:null, first_seen_at:"2026-10-20T00:00:00Z"}, openerRef:{current:null}, selectJob(){}
      })));
    `], { cwd: import.meta.dirname + "/..", encoding: "utf8" });
    assert.equal(probe.status, 0, probe.stderr);
    assert.ok(probe.stdout.includes(expected), probe.stdout);
  });
}
