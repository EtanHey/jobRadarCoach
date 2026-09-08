import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
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

test("verified official logos resolve with matching raster assets and provenance", () => {
  const manifest = JSON.parse(readFileSync(new URL("../public/companies/manifest.json", import.meta.url), "utf8"));
  for (const company of ["Pagaya Israel", "REAL DEV INC", "Shifters", "Tomax Think Academy", "Wix", "Moveo Group"]) {
    const entry = manifest.entries.find((item: { canonicalName: string }) => item.canonicalName === canonicalCompanyName(company));
    assert.ok(entry, `${company} is represented in the manifest`);
    assert.equal(entry.source.kind, "official-company-site");
    assert.equal(logoPathForCompany(company), `/companies/${entry.file}`);
    const bytes = readFileSync(new URL(`../public/companies/${entry.file}`, import.meta.url));
    assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
    assert.equal(createHash("sha256").update(bytes).digest("hex"), entry.sha256);
  }
});

test("fallback initials support words and non-Latin names", () => {
  assert.equal(companyInitials("Blue Vine"), "BV");
  assert.equal(companyInitials("אביב טכנולוגיות"), "אט");
  assert.equal(companyInitials("---"), "?");
});
