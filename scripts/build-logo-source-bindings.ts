// Offline, SELECT-only snapshot plus stored source pages. Never reads JD or emits contact data.
import { readFileSync, existsSync, writeFileSync } from "node:fs";
import { createHash } from "node:crypto";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { canonicalCompanyName, postingSourceCompanies } from "../ui/lib/company-logos";
import manifest from "../ui/public/companies/manifest.json";
import domains from "../ui/lib/company-logo-domains.json";
import type { CompanyLogoIdentity } from "../ui/lib/company-logos";

type Row = { id: string; company: string; url: string | null; apply_url: string | null };
const pins: Record<string, CompanyLogoIdentity> = {
  doit: { domains: ["doit.com"], collision: true, sourceCompanies: ["linkedin:doitintl", "greenhouse:doitintl"] },
  "moveo group": { domains: ["moveo.group"] },
  "pagaya israel": { domains: ["pagaya.com"] },
  "real dev inc": { domains: ["real.dev"] },
  shifters: { domains: ["shiftersai.com"] },
  "tomax think academy": { domains: ["tomax.io"] },
  wix: { domains: ["wix.com"] },
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
    // Known collisions require the reviewed pins above or verified employer-heading pages.
    if (!identity.collision) for (const row of rows.filter(row => canonicalCompanyName(row.company) === name)) {
      for (const company of postingSourceCompanies({ company: row.company, url: row.url, applyUrl: row.apply_url })) companies.add(company);
    }
    if (companies.size) identities[name].sourceCompanies = [...companies].sort();
  }
  return { identities, bindings, sourcePages };
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [snapshot, ...pageDirs] = process.argv.slice(2);
  if (!snapshot || !pageDirs.length) throw new Error("Usage: build-logo-source-bindings.ts <private snapshot.json> <source-page-dir>...");
  const result = buildLogoBindings(JSON.parse(readFileSync(snapshot, "utf8")), pageDirs);
  for (const [file, value] of [["company-logo-identities", result.identities], ["company-logo-source-bindings", result.bindings]] as const) {
    writeFileSync(new URL(`../ui/lib/${file}.json`, import.meta.url), JSON.stringify(Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b))), null, 2) + "\n");
  }
  console.log(JSON.stringify({ identities: Object.keys(result.identities).length, bindings: Object.keys(result.bindings).length, sourcePages: result.sourcePages }, null, 2));
}
