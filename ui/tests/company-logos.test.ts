import assert from "node:assert/strict";
import { test } from "node:test";
import { canonicalCompanyName, companyInitials, logoPathForCompany } from "../lib/company-logos";

test("company names canonicalize without guessing corporate aliases", () => {
  assert.equal(canonicalCompanyName("  ACME\t Labs  "), "acme labs");
  assert.notEqual(canonicalCompanyName("Acme, Inc."), canonicalCompanyName("Acme"));
});

test("catalog resolves captured names and leaves unknown identities explicit", () => {
  assert.match(logoPathForCompany("MeeBoss") ?? "", /^\/companies\/meeboss-[a-f0-9]{10}\.(?:jpg|png|gif|webp)$/);
  assert.equal(logoPathForCompany("Definitely Not A Captured Company"), null);
});

test("fallback initials support words and non-Latin names", () => {
  assert.equal(companyInitials("Blue Vine"), "BV");
  assert.equal(companyInitials("אביב טכנולוגיות"), "אט");
  assert.equal(companyInitials("---"), "?");
});
