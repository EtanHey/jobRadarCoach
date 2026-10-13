import assert from "node:assert/strict";
import { test } from "node:test";
import { auditLogoCollisions } from "../../scripts/audit-logo-collisions";
import catalog from "../lib/company-logo-catalog.json";
import domains from "../lib/company-logo-domains.json";

test("the collision audit inventories every shipped key even without matching postings", () => {
  assert.deepEqual(auditLogoCollisions([]).map(entry => entry.name), [...new Set([...Object.keys(catalog), ...Object.keys(domains)])].sort());
});

test("the audit reports competing domains but preserves missing evidence explicitly", () => {
  const rows = [
    { id: "synthetic-app", company: "Doit", url: "https://www.linkedin.com/jobs/view/1", apply_url: "https://doit.app/jobs/1", raw_jd: "We use Node.js." },
    { id: "synthetic-cloud", company: " DoiT ", url: "https://www.linkedin.com/jobs/view/2", apply_url: "https://doit.com/jobs/1", raw_jd: null },
    { id: "synthetic-unknown", company: "Doit", url: "https://www.linkedin.com/jobs/view/3", apply_url: null, raw_jd: null },
  ];
  const doit = auditLogoCollisions(rows).find(entry => entry.name === "doit")!;
  assert.deepEqual(doit.expected, ["doit.com"]);
  assert.deepEqual(doit.postings, [
    { id: "synthetic-app", evidence: ["doit.app"], sourceCompanies: [], conflicts: ["doit.app"] },
    { id: "synthetic-cloud", evidence: ["doit.com"], sourceCompanies: [], conflicts: [] },
    { id: "synthetic-unknown", evidence: [], sourceCompanies: [], conflicts: [] },
  ]);
});
