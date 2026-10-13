import assert from "node:assert/strict";
import { test } from "node:test";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { createHash } from "node:crypto";
import { buildLogoRestorations, type LogoRestorationEvidence } from "../../scripts/build-logo-source-bindings";
import { resolveCompanyLogo } from "../lib/company-logos";

const hash = (s: string) => createHash("sha256").update(s).digest("hex");
function fixture(run: (dir: string, proof: LogoRestorationEvidence, row: { id: string; company: string; url: string; apply_url: null }) => void) {
  const dir = mkdtempSync(join(tmpdir(), "logo-ownership-"));
  const homepage = '<a href="https://www.linkedin.com/company/synthetic-owner/">Company</a>';
  const posting = '<a class="topcard__org-name-link" href="https://www.linkedin.com/company/synthetic-owner/">Synthetic Co</a>';
  writeFileSync(join(dir, "homepage.html"), homepage);
  writeFileSync(join(dir, "synthetic-posting.html"), posting);
  const proof = { domain: "synthetic.test", website: "https://synthetic.test/", homepageFile: "homepage.html", homepageSha256: hash(homepage), sourceCompany: "linkedin:synthetic-owner", employerProfile: "https://www.linkedin.com/company/synthetic-owner/", employerWebsite: "https://synthetic.test/", postings: [{ postingId: "synthetic-posting", pageSha256: hash(posting) }] };
  try { run(dir, proof, { id: "synthetic-posting", company: "Synthetic Co", url: "https://linkedin.com/jobs/view/1", apply_url: null }); }
  finally { rmSync(dir, { recursive: true }); }
}

test("restoration requires a reviewed employer Website pin and matching verified posting heading", () => fixture((dir, proof, row) => {
  const result = buildLogoRestorations([row], [dir], dir, { "synthetic co": proof });
  assert.deepEqual(result.domains, { "synthetic co": "synthetic.test" });
  assert.deepEqual(result.bindings, { "synthetic-posting": "linkedin:synthetic-owner" });
  assert.equal(result.identities["synthetic co"].collision, true);
  const options = { logoDevKey: "pk_synthetic_fixture", domainMap: result.domains, identities: result.identities };
  assert.equal(resolveCompanyLogo({ company: row.company, sourceCompany: "linkedin:synthetic-owner" }, options)?.kind, "logo-dev");
  assert.equal(resolveCompanyLogo({ company: row.company }, options), null);
  assert.equal(resolveCompanyLogo({ company: row.company, sourceCompany: "linkedin:unrelated" }, options), null);
  assert.equal(resolveCompanyLogo({ company: row.company, sourceCompany: "linkedin:synthetic-owner", url: "https://unrelated.test/job" }, options), null);
  assert.equal(resolveCompanyLogo({ company: row.company, rawJd: "https://synthetic.test" }, options), null);
}));

test("changed page bytes, wrong employer, missing pages and unrelated website fail closed", () => fixture((dir, proof, row) => {
  for (const changed of [
    { ...proof, homepageSha256: "0".repeat(64) },
    { ...proof, sourceCompany: "linkedin:unrelated" },
    { ...proof, website: "https://unrelated.test/" },
    { ...proof, employerWebsite: "https://unrelated.test/" },
    { ...proof, employerProfile: "https://linkedin.com/company/unrelated/" },
    { ...proof, website: "https://synthetic.test@unrelated.test/" },
    { ...proof, postings: [{ postingId: "missing", pageSha256: "0".repeat(64) }] },
    { ...proof, postings: [{ postingId: row.id, pageSha256: "0".repeat(64) }] },
  ]) assert.throws(() => buildLogoRestorations([row], [dir], dir, { "synthetic co": changed }), /Unproven logo restoration/);
  assert.throws(() => buildLogoRestorations([{ ...row, company: "Other Co" }], [dir], dir, { "synthetic co": proof }), /Unproven logo restoration/);
}));

test("reviewed employer Website field identifies the domain without a social link on its homepage", () => fixture((dir, proof, row) => {
  const homepage = "<h1>Synthetic Co careers</h1>";
  writeFileSync(join(dir, "homepage.html"), homepage);
  const result = buildLogoRestorations([row], [dir], dir, { "synthetic co": { ...proof, homepageSha256: hash(homepage) } });
  assert.equal(result.domains["synthetic co"], "synthetic.test");
}));

test("an employer Website subdomain belongs to its domain, while a suffix lookalike does not", () => fixture((dir, proof, row) => {
  assert.equal(buildLogoRestorations([row], [dir], dir, { "synthetic co": { ...proof, employerWebsite: "https://careers.synthetic.test/" } }).domains["synthetic co"], "synthetic.test");
  assert.throws(() => buildLogoRestorations([row], [dir], dir, { "synthetic co": { ...proof, employerWebsite: "https://synthetic.test.unrelated.test/" } }), /Unproven logo restoration/);
}));

test("shipped 1Password restoration grants its verified employer and denies an unbound namesake", () => {
  const source = resolveCompanyLogo({ company: "1Password", sourceCompany: "linkedin:1password" }, { logoDevKey: "pk_synthetic_fixture" });
  assert.equal(source?.kind, "logo-dev");
  assert.equal(source && new URL(source.src).pathname, "/1password.com");
  assert.equal(resolveCompanyLogo({ company: "1Password", url: "https://linkedin.com/jobs/view/synthetic" }, { logoDevKey: "pk_synthetic_fixture" }), null);
});
