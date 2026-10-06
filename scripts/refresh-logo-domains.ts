import { readFile, writeFile, rename } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { canonicalCompanyName } from "../ui/lib/company-logos";

export type DomainMap = Record<string, string | null>;
export type SearchCandidate = { name?: unknown; domain?: unknown };

export function validLogoDomain(value: unknown): value is string {
  if (typeof value !== "string" || value.length > 253 || /^\d+(?:\.\d+)+$/.test(value)) return false;
  const labels = value.split(".");
  return labels.length >= 2 && labels.every(label => /^[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?$/.test(label));
}

// Lead's conservative name/domain resemblance rule; this is not a site-ownership verification.
const suffixWords = new Set("inc ltd llc corp co company technologies tech solutions group labs lab software systems holdings international israel il global the of and".split(" "));

export function ownsDomain(company: string, domain: string): boolean {
  if (!validLogoDomain(domain)) return false;
  const label = domain.split(".")[0].replace(/[^a-z0-9]/g, "");
  if (label.length < 2) return false;
  const words = canonicalCompanyName(company).match(/[a-z0-9]+/g) ?? [];
  const core = words.filter(word => !suffixWords.has(word));
  const joined = [words.join(""), core.join("")];
  const initials = [words, words.filter(word => !["of", "and", "the"].includes(word))].map(tokens => tokens.map(word => word[0]).join(""));
  return joined.some(name => name.length > 0 && (name.includes(label) || label.includes(name)))
    || core.some(word => word.length >= 4 && label.includes(word))
    || initials.includes(label);
}

export function confidentDomain(company: string, candidates: SearchCandidate[]): string | null {
  const name = canonicalCompanyName(company);
  for (const candidate of candidates) {
    if (!candidate || !validLogoDomain(candidate.domain) || !ownsDomain(company, candidate.domain)) continue;
    if ((typeof candidate.name === "string" && canonicalCompanyName(candidate.name) === name)
      || candidate.domain.split(".")[0] === name) return candidate.domain;
  }
  return null;
}

export async function refreshDomains(companies: string[], existing: DomainMap, key: string,
  fetcher: typeof fetch = fetch, wait: (ms: number) => Promise<void> = ms => new Promise(resolve => setTimeout(resolve, ms))): Promise<DomainMap> {
  const result: DomainMap = Object.assign(Object.create(null), existing);
  let requested = false;
  for (const company of companies) {
    const name = canonicalCompanyName(company);
    if (!name || Object.hasOwn(result, name)) continue;
    if (requested) await wait(1000); // At least one second after the previous response, including failures.
    requested = true;
    const url = new URL("https://api.logo.dev/search");
    url.search = new URLSearchParams({ q: company.trim(), strategy: "match" }).toString();
    let response: Response;
    try {
      response = await fetcher(url, { headers: { Authorization: `Bearer ${key}` }, redirect: "error", signal: AbortSignal.timeout(10000) });
    } catch { throw new Error("Brand Search request failed"); }
    if (!response.ok) throw new Error(`Brand Search failed (HTTP ${response.status})`);
    let candidates: unknown;
    try { candidates = await response.json(); } catch { throw new Error("Invalid Brand Search response"); }
    if (!Array.isArray(candidates) || candidates.some(candidate => !candidate || typeof candidate !== "object"
      || typeof candidate.name !== "string" || typeof candidate.domain !== "string")) {
      throw new Error("Invalid Brand Search response");
    }
    result[name] = confidentDomain(company, candidates);
  }
  return Object.fromEntries(Object.entries(result).sort(([a], [b]) => a.localeCompare(b, "en-US")));
}

async function main() {
  const [inputPath, outputPath = "../ui/lib/company-logo-domains.json"] = process.argv.slice(2);
  const key = process.env.LOGO_DEV_SECRET_KEY;
  if (!inputPath || !key?.startsWith("sk_")) throw new Error("Provide a company-names JSON path and LOGO_DEV_SECRET_KEY");
  const companies: unknown = JSON.parse(await readFile(inputPath, "utf8"));
  if (!Array.isArray(companies) || !companies.every(name => typeof name === "string")) throw new Error("Expected a JSON array of company names");
  let existing: DomainMap = {};
  try { existing = JSON.parse(await readFile(outputPath, "utf8")); } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== "ENOENT") throw error;
  }
  if (!existing || Array.isArray(existing) || typeof existing !== "object"
    || Object.entries(existing).some(([name, domain]) => name !== canonicalCompanyName(name) || (domain !== null && !validLogoDomain(domain)))) {
    throw new Error("Invalid existing domain map");
  }
  const map = await refreshDomains(companies, existing, key);
  const temporary = `${outputPath}.${process.pid}.tmp`;
  await writeFile(temporary, `${JSON.stringify(map, null, 2)}\n`);
  await rename(temporary, outputPath);
  console.log(`Domain map saved (${Object.keys(map).length} entries)`);
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(() => { console.error("Logo domain refresh failed; output unchanged. Check input, key and provider availability."); process.exitCode = 1; });
}
