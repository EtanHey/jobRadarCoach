import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { test } from "node:test";
import { employerLabel } from "../lib/employer-identity";
import { EmployerIdentitySchema } from "../lib/contracts";
import aliases from "../lib/employer-aliases.json";

for (const [publisher, employer, expected] of [
  ["EngRadar", "Monday.com", "Monday.com via EngRadar"],
  ["Torentify", null, "Torentify (agency — client undisclosed)"],
  ["Wix", "Wix", "Wix"],
  ["1Password", null, "1Password"],
  ["Aiven", null, "Aiven"],
  ["AT&T Israel R&D Center", null, "AT&T Israel R&D Center"],
  ["BMC Software", "BMC", "BMC Software"],
  ["Alice (Formerly ActiveFence)", "Alice", "Alice (Formerly ActiveFence)"],
  ["SWAKIO™", "SWAKIO", "SWAKIO™"],
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
    assert.ok(probe.stdout.includes(expected.replaceAll("&", "&amp;")), probe.stdout);
  });
}

test("unknown unlisted publisher uses an agency label only with explicit evidence", () => {
  const identity = { publisher: "Talent Bridge", hiring_employer: null, employer_evidence: null,
    resolver_version: "2", agency_evidence: "Talent Bridge is a staffing firm." };
  assert.equal(employerLabel({ company: "Talent Bridge", employer_identity: identity }),
    "Talent Bridge (agency — client undisclosed)");
});

test("legacy unknown nonagency and mismatched metadata retain the publisher", () => {
  assert.equal(employerLabel({ company: "1Password" }), "1Password");
  assert.equal(employerLabel({ company: "1Password", employer_identity: {
    publisher: "Torentify", hiring_employer: null, employer_evidence: null, resolver_version: "1",
  } }), "1Password");
});

test("all reviewed aliases avoid via relationships for legacy and version 2 metadata", () => {
  for (const [publisher, names] of Object.entries(aliases)) {
    for (const employer of names) {
      for (const relationship of [undefined, "alias"] as const) {
        const identity = EmployerIdentitySchema.parse({ publisher, hiring_employer: employer,
          employer_evidence: `${employer} is hiring`, resolver_version: "2", relationship });
        assert.equal(employerLabel({ company: publisher, employer_identity: identity }), publisher);
      }
    }
  }
});

test("the API identity schema preserves explicit agency evidence", () => {
  const identity = EmployerIdentitySchema.parse({ publisher: "Talent Bridge", hiring_employer: null,
    employer_evidence: null, resolver_version: "2", relationship: "unknown",
    agency_evidence: "Our client is seeking an engineer." });
  assert.equal(identity.relationship, "unknown");
  assert.equal(employerLabel({ company: identity.publisher, employer_identity: identity }),
    "Talent Bridge (agency — client undisclosed)");
});


test("r10 resolver output keeps reviewer quote and first-person reproducers publisher-only", () => {
  const probe = spawnSync("python3", ["-c", `
import json
from pathlib import Path
from scraper.employer_identity import resolve_employer
cases = json.loads(Path('test_support/fixtures/employer_identity_r10.json').read_text())
print(json.dumps([resolve_employer('Acme Labs', row['jd'], source)
                  for row in cases for source in ['linkedin', 'greenhouse']]))
`], { cwd: import.meta.dirname + "/../..", encoding: "utf8" });
  assert.equal(probe.status, 0, probe.stderr);
  const identities = EmployerIdentitySchema.array().parse(JSON.parse(probe.stdout));
  assert.equal(identities.length, 20);
  for (const identity of identities) {
    assert.equal(identity.agency_evidence, null);
    assert.equal(employerLabel({ company: identity.publisher, employer_identity: identity }), "Acme Labs");
  }
});

test("r11 first-party allowlist keeps both reviewers and new attempts publisher-only", () => {
  const probe = spawnSync("python3", ["-c", `
import json
from pathlib import Path
from scraper.employer_identity import resolve_employer
cases = json.loads(Path('test_support/fixtures/employer_identity_r11.json').read_text())
print(json.dumps([resolve_employer(row['publisher'], row['jd'], source)
                  for row in cases for source in ['linkedin', 'greenhouse']]))
`], { cwd: import.meta.dirname + "/../..", encoding: "utf8" });
  assert.equal(probe.status, 0, probe.stderr);
  const identities = EmployerIdentitySchema.array().parse(JSON.parse(probe.stdout));
  assert.equal(identities.length, 60);
  for (const identity of identities) {
    assert.equal(identity.agency_evidence, null);
    assert.equal(employerLabel({ company: identity.publisher, employer_identity: identity }), identity.publisher);
  }
});
