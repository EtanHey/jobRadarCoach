// Offline, SELECT-only snapshot plus stored source pages. Never reads JD or emits contact data.
import { readFileSync, existsSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { canonicalCompanyName, postingSourceCompanies } from "../ui/lib/company-logos";
import { companyLogoIdentityPins } from "../ui/lib/company-logo-identity-pins";
import manifest from "../ui/public/companies/manifest.json";
import domains from "../ui/lib/company-logo-domains.json";
import existingIdentities from "../ui/lib/company-logo-identities.json";
import existingBindings from "../ui/lib/company-logo-source-bindings.json";
import restorationPins from "./company-logo-restorations.json";
import type { CompanyLogoIdentity } from "../ui/lib/company-logos";

type Row = { id: string; company: string; url: string | null; apply_url: string | null };
const pins: Record<string, CompanyLogoIdentity> = {
  ...Object.fromEntries(Object.entries(restorationPins as Record<string, LogoRestorationEvidence>).map(([name, proof]) => [name, {
    domains: [proof.domain], sourceCompanies: [proof.sourceCompany], collision: true,
  }])),
  ...companyLogoIdentityPins,
};

export function buildLogoBindings(rows: Row[], pageDirs: string[]) {
  const bindings: Record<string, string> = {};
  const sourcePages: Record<string, { sha256: string; company: string }> = {};
  for (const row of rows) {
    const path = pageDirs.map(dir => join(dir, `${row.id}.html`)).find(existsSync);
    if (!path) continue;
    const bytes = readFileSync(path), html = bytes.toString("utf8");
    // Only the employer heading; related-company links elsewhere on the page are irrelevant.
    const anchor = html.match(/<a\b[^>]*class="[^"]*topcard__org-name-link[^"]*"[^>]*>([\s\S]*?)<\/a>/);
    const href = anchor?.[0].match(/href="([^"]+)"/)?.[1];
    const label = anchor?.[1].replace(/<[^>]+>/g, "").replaceAll("&amp;", "&").trim();
    if (!href || !label || canonicalCompanyName(label) !== canonicalCompanyName(row.company)) continue;
    const company = postingSourceCompanies({ company: row.company, url: href })[0];
    if (!company?.startsWith("linkedin:")) continue;
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    const asset = manifest.entries.find(entry => entry.canonicalName === canonicalCompanyName(row.company));
    if (asset?.source.postingId === row.id && asset.source.kind === "linkedin-public-job-page" && asset.source.pageSha256 !== sha256) {
      throw new Error(`Manifest source page hash mismatch: ${row.id}`);
    }
    bindings[row.id] = company;
    sourcePages[row.id] = { sha256, company };
  }
  const identities: Record<string, CompanyLogoIdentity> = { ...pins };
  for (const entry of manifest.entries) {
    const name = entry.canonicalName;
    const mapped = (domains as Record<string, string | null>)[name];
    const identity = identities[name] ?? { domains: mapped ? [mapped] : [] };
    const pid = entry.source.postingId;
    identities[name] = { ...identity, ...(pid ? { postingIds: [pid] } : {}) };
    const companies = new Set(identity.sourceCompanies);
    if (pid && bindings[pid]) companies.add(bindings[pid]);
    // Existing unambiguous catalog names may bind their snapshot's structured ATS tenants.
    // Known collisions require the reviewed identity pins or verified employer-heading pages.
    if (!identity.collision) for (const row of rows.filter(row => canonicalCompanyName(row.company) === name)) {
      for (const company of postingSourceCompanies({ company: row.company, url: row.url, applyUrl: row.apply_url })) companies.add(company);
    }
    if (companies.size) identities[name].sourceCompanies = [...companies].sort();
  }
  return { identities, bindings, sourcePages };
}

export type LogoRestorationEvidence = {
  domain: string; website: string; homepageFile: string; homepageSha256: string;
  employerProfile: string; employerWebsite: string;
  sourceCompany: string; postings: { postingId: string; pageSha256: string }[];
};

/** Reviewed employer-profile Website pins plus hash-verified posting headings; no name lookup. */
export function buildLogoRestorations(rows: Row[], pageDirs: string[], homepageDir: string, proofs: Record<string, LogoRestorationEvidence>) {
  const verified = buildLogoBindings(rows, pageDirs);
  const restoredDomains: Record<string, string> = {};
  const restoredIdentities: Record<string, CompanyLogoIdentity> = {};
  const restoredBindings: Record<string, string> = {};
  for (const [name, proof] of Object.entries(proofs)) {
    const refuse = () => { throw new Error(`Unproven logo restoration: ${name}`); };
    const website = new URL(proof.website);
    const employerWebsite = new URL(proof.employerWebsite);
    if (canonicalCompanyName(name) !== name || !proof.sourceCompany.startsWith("linkedin:")
      || website.protocol !== "https:" || website.username || website.password
      || website.hostname.replace(/^www\./, "") !== proof.domain || !proof.postings.length
      || !["http:", "https:"].includes(employerWebsite.protocol) || employerWebsite.username || employerWebsite.password
      || !(employerWebsite.hostname === proof.domain || employerWebsite.hostname.endsWith(`.${proof.domain}`))
      || !postingSourceCompanies({ company: name, url: proof.employerProfile }).includes(proof.sourceCompany)) refuse();
    const bytes = readFileSync(join(homepageDir, proof.homepageFile));
    if (createHash("sha256").update(bytes).digest("hex") !== proof.homepageSha256) refuse();
    // The reviewed profile's explicit Website field is authoritative; a site's social links
    // are corroboration only. A homepage title, JD mention or inferred company slug is not proof.
    for (const posting of proof.postings) {
      const row = rows.find(row => row.id === posting.postingId);
      const page = verified.sourcePages[posting.postingId];
      if (!row || canonicalCompanyName(row.company) !== name || !page
        || page.company !== proof.sourceCompany || page.sha256 !== posting.pageSha256) refuse();
      restoredBindings[posting.postingId] = proof.sourceCompany;
    }
    restoredDomains[name] = proof.domain;
    // Positive proof is required even for names not previously known to collide.
    restoredIdentities[name] = { domains: [proof.domain], sourceCompanies: [proof.sourceCompany], collision: true };
  }
  return { domains: restoredDomains, identities: restoredIdentities, bindings: restoredBindings };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  if (process.argv[2] === "--restore") {
    const [, , , snapshot, proofFile, homepageDir, ...pageDirs] = process.argv;
    if (!snapshot || !proofFile || !homepageDir || !pageDirs.length) throw new Error("Usage: build-logo-source-bindings.ts --restore <snapshot.json> <proofs.json> <homepage-dir> <source-page-dir>...");
    const result = buildLogoRestorations(JSON.parse(readFileSync(snapshot, "utf8")), pageDirs, homepageDir, JSON.parse(readFileSync(proofFile, "utf8")));
    // Validate all evidence and preservation constraints before touching any generated file.
    for (const [name, domain] of Object.entries(result.domains)) {
      const existing = (existingIdentities as Record<string, CompanyLogoIdentity>)[name];
      if ((existing && JSON.stringify(existing) !== JSON.stringify(result.identities[name]))
        || ((domains as Record<string, string | null>)[name] ?? domain) !== domain) throw new Error(`Existing logo identity/domain requires separate review: ${name}`);
    }
    for (const [id, company] of Object.entries(result.bindings)) {
      if (Object.hasOwn(existingBindings, id) && (existingBindings as Record<string, string>)[id] !== company) throw new Error(`Existing posting binding conflicts: ${id}`);
    }
    for (const [file, value] of [["company-logo-domains", { ...domains, ...result.domains }], ["company-logo-identities", { ...existingIdentities, ...result.identities }], ["company-logo-source-bindings", { ...existingBindings, ...result.bindings }]] as const) {
      writeFileSync(new URL(`../ui/lib/${file}.json`, import.meta.url), JSON.stringify(Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))), null, 2) + "\n");
    }
    console.log(JSON.stringify({ restored: Object.keys(result.domains).length, bindings: Object.keys(result.bindings).length }));
  } else {
    const [snapshot, ...pageDirs] = process.argv.slice(2);
    if (!snapshot || !pageDirs.length) throw new Error("Usage: build-logo-source-bindings.ts <private snapshot.json> <source-page-dir>...");
    const result = buildLogoBindings(JSON.parse(readFileSync(snapshot, "utf8")), pageDirs);
    for (const [file, value] of [["company-logo-identities", result.identities], ["company-logo-source-bindings", result.bindings]] as const) {
      writeFileSync(new URL(`../ui/lib/${file}.json`, import.meta.url), JSON.stringify(Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))), null, 2) + "\n");
    }
    console.log(JSON.stringify({ identities: Object.keys(result.identities).length, bindings: Object.keys(result.bindings).length, sourcePages: result.sourcePages }, null, 2));
  }
}
