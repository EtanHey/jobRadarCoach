import assert from "node:assert/strict";
import { test } from "node:test";
import { resolveCompanyLogo } from "../lib/company-logos";
import fixture from "./fixtures/logo-coverage-2026-10-07.json";
import identitiesJson from "../lib/company-logo-identities.json";
import sourceBindings from "../lib/company-logo-source-bindings.json";
import { buildLogoBindings } from "../../scripts/build-logo-source-bindings";
import type { CompanyLogoIdentity } from "../lib/company-logos";

const options = { logoDevKey: "pk_synthetic_fixture" };
const wrongPosting = "f0dc6b0d-5897-4e50-9946-5e91aae3e321";

test("frozen SELECT-only 1514-row snapshot preserves at least 95% of previous catalog/domain sources", () => {
  assert.equal(fixture.length, 1514);
  const previous = fixture.filter(row => row.previous && row.input.postingId !== wrongPosting);
  assert.equal(previous.length, 895, "excludes only the independently verified wrong Doit image; name searches are not a catalog/domain source");
  const retained = previous.filter(row => {
    const source = resolveCompanyLogo(row.input, options);
    return source !== null && row.previous !== null && source.kind === row.previous.kind && (source.kind === "logo-dev" ? new URL(source.src).pathname : source.src) === row.previous.path;
  });
  assert.ok(retained.length / previous.length >= 0.95, `${retained.length}/${previous.length} retained`);
});

test("snapshot summary and loaded drawer agree for every row despite partner/negation/userinfo JD", () => {
  for (const { input } of fixture) {
    const card = resolveCompanyLogo(input, options);
    for (const rawJd of ["Our cloud partner is DoiT (https://doit.com).", "We are not affiliated with doit.com. Contact support@doit.com.", "See https://doit.com@attacker.example/jobs/1; partner wix.app."]) {
      assert.deepEqual(resolveCompanyLogo({ ...input, rawJd }, options), card, input.postingId);
    }
  }
});

test("all six verified DoiT rows keep their logo and the homonym stays initials", () => {
  const doit = fixture.filter(row => row.input.company.toLowerCase() === "doit");
  assert.equal(doit.length, 7);
  for (const { input } of doit) {
    if (input.postingId === wrongPosting) assert.equal(resolveCompanyLogo(input, options), null);
    else assert.deepEqual(resolveCompanyLogo(input, options), { kind: "catalog", src: "/companies/doit-1a4c4090b4.jpg" });
  }
});

test("all observed multiple-employer names are collision guarded", () => {
  const grouped = new Map<string, Set<string>>();
  for (const { input } of fixture) {
    const source = (sourceBindings as Record<string, string>)[input.postingId];
    if (!source) continue;
    const name = input.company.toLowerCase(), set = grouped.get(name) ?? new Set();
    set.add(source); grouped.set(name, set);
  }
  const collisions = [...grouped].filter(([, companies]) => companies.size > 1).map(([name]) => name);
  assert.deepEqual(collisions, ["doit"]);
  for (const name of collisions) assert.equal((identitiesJson as Record<string, CompanyLogoIdentity>)[name].collision, true);
});

test("offline binding build cannot grant employer identity from JD or missing source pages", () => {
  const result = buildLogoBindings([{ id: "unverified", company: "Doit", url: "https://linkedin.com/jobs/view/1", apply_url: null }], []);
  assert.deepEqual(result.bindings, {});
  assert.ok(result.identities.doit.collision);
});
