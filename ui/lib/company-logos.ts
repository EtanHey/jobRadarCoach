import domainsJson from "./company-logo-domains.json";
import catalogJson from "./company-logo-catalog.json";
import identitiesJson from "./company-logo-identities.json";
import sourceBindingsJson from "./company-logo-source-bindings.json";
import { companyLogoOverrides, type CompanyLogoOverride } from "./company-logo-overrides";

export type CompanyLogoDomainMap = Readonly<Record<string, string | null>>;
const domains: CompanyLogoDomainMap = domainsJson;
const catalog = catalogJson as Record<string, string>;

export type CompanyLogoSource = { kind: "catalog" | "override" | "logo-dev"; src: string };
export type CompanyLogoInput = { company: string; applyUrl?: string | null; url?: string | null; rawJd?: string | null; postingId?: string | null; sourceCompany?: string | null };
export type CompanyLogoIdentity = { domains: readonly string[]; sourceCompanies?: readonly string[]; postingIds?: readonly string[]; collision?: boolean };
const sourceBindings: Readonly<Record<string, string>> = sourceBindingsJson;
const identities: Readonly<Record<string, CompanyLogoIdentity>> = identitiesJson;
export type CompanyLogoOptions = { logoDevKey?: string; domainMap?: CompanyLogoDomainMap; overrides?: Readonly<Record<string, CompanyLogoOverride>>; identities?: Readonly<Record<string, CompanyLogoIdentity>> };

// Rendered at up to 64 CSS px, so one 2x request serves every size and stays a single cache entry.
const LOGO_DEV_SIZE = 128;

// Hosts that serve postings for many employers; their domain never identifies the company.
const sharedJobHosts = [
  "greenhouse.io", "lever.co", "ashbyhq.com", "workable.com", "comeet.com", "comeet.co", "smartrecruiters.com",
  "myworkdayjobs.com", "myworkdaysite.com", "workday.com", "linkedin.com", "indeed.com", "glassdoor.com",
  "bamboohr.com", "recruitee.com", "breezy.hr", "jobvite.com", "icims.com", "teamtailor.com", "personio.de",
  "personio.com", "pinpointhq.com", "rippling.com", "rippling-ats.com", "applytojob.com", "jazzhr.com",
  "taleo.net", "successfactors.com", "successfactors.eu", "oraclecloud.com", "wellfound.com", "ycombinator.com",
  "builtin.com", "firststage.co", "hibob.com", "gem.com", "dover.com", "jobs.ashbyhq.com", "google.com", "notion.site",
];
const secondLevelLabels = new Set(["co", "com", "org", "net", "ac", "gov", "edu"]);
const genericCompanyWords = new Set(["the", "inc", "ltd", "llc", "group", "labs", "lab", "technologies", "technology", "tech", "security", "israel", "software", "systems", "solutions", "company", "global", "international", "ai", "io", "app", "com"]);

export function canonicalCompanyName(company: string): string {
  return company.normalize("NFKC").trim().toLocaleLowerCase("en-US").replace(/\s+/g, " ");
}

export function companyInitials(company: string): string {
  const words = company.match(/[\p{L}\p{N}]+/gu) ?? [];
  return words.slice(0, 2).map((word) => [...word][0]).join("").toLocaleUpperCase("en-US") || "?";
}

function registrableDomain(hostname: string): string | null {
  const labels = hostname.replace(/\.$/, "").split(".");
  const [tld = "", second = ""] = labels.slice(-2).reverse();
  if (labels.length < 2 || labels.some((label) => !/^[a-z0-9-]+$/.test(label)) || /^\d+$/.test(tld)) return null;
  const take = labels.length >= 3 && tld.length === 2 && secondLevelLabels.has(second) ? 3 : 2;
  return labels.slice(-take).join(".");
}

/** The company's own registrable domain from its posting URLs, or null when no URL is trustworthy. */
export function companyDomain(company: string, urls: readonly (string | null | undefined)[]): string | null {
  const words = (canonicalCompanyName(company).match(/[a-z0-9]+/g) ?? []);
  const compact = words.join("");
  if (!compact) return null;
  for (const raw of urls) {
    if (!raw) continue;
    let hostname: string;
    try {
      const parsed = new URL(raw);
      if (parsed.protocol !== "https:" && parsed.protocol !== "http:") continue;
      hostname = parsed.hostname.toLowerCase();
    } catch {
      continue;
    }
    if (sharedJobHosts.some((host) => hostname === host || hostname.endsWith(`.${host}`))) continue;
    const domain = registrableDomain(hostname);
    if (!domain) continue;
    const label = domain.split(".")[0];
    const flatLabel = label.replace(/-/g, "");
    const named = flatLabel === compact
      || (flatLabel.length >= 4 && !genericCompanyWords.has(flatLabel) && compact.startsWith(flatLabel))
      || words.some((word) => word.length >= 3 && !genericCompanyWords.has(word) && (word === label || word === flatLabel));
    if (named) return domain;
  }
  return null;
}

function logoDevUrl(path: string, key: string): string {
  const params = new URLSearchParams({ token: key, size: String(LOGO_DEV_SIZE), format: "png", theme: "light", fallback: "404" });
  return `https://img.logo.dev/${path}?${params}`;
}

/** Only structured posting/apply URLs identify domains. Free-text JD is deliberately ignored. */
export function postingCompanyDomains(input: CompanyLogoInput): string[] {
  const found = new Set<string>();
  for (const url of [input.applyUrl, input.url]) {
    if (!url) continue;
    try {
      const parsed = new URL(url);
      if (!["https:", "http:"].includes(parsed.protocol)) continue;
      const host = parsed.hostname.toLowerCase();
      if (sharedJobHosts.some(shared => host === shared || host.endsWith(`.${shared}`))) continue;
      const domain = registrableDomain(host);
      if (domain) found.add(domain);
    } catch { /* Invalid URLs provide no identity evidence. */ }
  }
  return [...found];
}

/** ATS tenant paths are structured employer identifiers, never shared-host domain evidence. */
export function postingSourceCompanies(input: CompanyLogoInput): string[] {
  const found = new Set<string>();
  if (input.sourceCompany) found.add(input.sourceCompany.toLowerCase());
  const bound = input.postingId ? own(sourceBindings, input.postingId) : undefined;
  if (bound) found.add(bound);
  for (const raw of [input.applyUrl, input.url]) {
    if (!raw) continue;
    try {
      const url = new URL(raw);
      if (!["https:", "http:"].includes(url.protocol) || url.username || url.password) continue;
      const host = url.hostname.toLowerCase(), parts = url.pathname.split("/").filter(Boolean);
      const slug = parts[0]?.toLowerCase();
      if (!slug || !/^[a-z0-9_-]+$/.test(slug)) continue;
      if (["boards.greenhouse.io", "job-boards.greenhouse.io", "boards.eu.greenhouse.io", "job-boards.eu.greenhouse.io"].includes(host)) found.add(`greenhouse:${slug}`);
      else if (host === "jobs.lever.co" || host === "jobs.eu.lever.co") found.add(`lever:${slug}`);
      else if (host === "jobs.ashbyhq.com") found.add(`ashby:${slug}`);
      else if (host === "apply.workable.com") found.add(`workable:${slug}`);
      else if (host.endsWith(".firststage.co")) found.add(`firststage:${host.split(".")[0]}`);
      else if ((host === "linkedin.com" || host.endsWith(".linkedin.com")) && parts[0] === "company" && parts[1]) found.add(`linkedin:${parts[1].toLowerCase()}`);
    } catch { /* Invalid URLs provide no source-company identifier. */ }
  }
  return [...found];
}

const own = <T,>(map: Readonly<Record<string, T>>, name: string): T | undefined => Object.hasOwn(map, name) ? map[name] : undefined;

/** Identity-qualified overrides/catalog, then the posting's own domain; uncertainty renders initials. */
export function resolveCompanyLogo(input: CompanyLogoInput, options: CompanyLogoOptions = {}): CompanyLogoSource | null {
  const name = canonicalCompanyName(input.company);
  const key = options.logoDevKey?.startsWith("pk_") ? options.logoDevKey : null;
  const override = own(options.overrides ?? companyLogoOverrides, name);
  if (override?.kind === "initials" || !name) return null;
  const identity = own(options.identities ?? identities, name);
  const mapped = own(options.domainMap ?? domains, name);
  const expected = override?.kind === "domain" ? [override.domain] : identity?.domains ?? (mapped ? [mapped] : []);
  const evidence = postingCompanyDomains(input);
  const companies = postingSourceCompanies(input);
  const expectedCompanies = identity?.sourceCompanies ?? [];
  const companyConflict = expectedCompanies.length > 0 && companies.some(company => !expectedCompanies.includes(company));
  if (companyConflict) return null;
  // Two competing employer domains cannot be resolved by URL order or by a name match.
  if (evidence.length > 1) return null;
  const domain = evidence[0];
  const sourceMatch = companies.some(company => expectedCompanies.includes(company)) || !!(input.postingId && identity?.postingIds?.includes(input.postingId));
  const domainMatch = !!domain && expected.includes(domain);
  const domainConflict = !!domain && (expected.length > 0 ? !domainMatch : !companyDomain(input.company, [input.applyUrl, input.url]));
  const qualified = !domainConflict && (domainMatch || sourceMatch || !identity?.collision);
  if (override?.kind === "file") return qualified ? { kind: "override", src: override.src } : null;
  if (override?.kind === "domain") return qualified && key ? { kind: "logo-dev", src: logoDevUrl(override.domain, key) } : null;
  const curated = own(catalog, name);
  if (curated && qualified) return { kind: "catalog", src: curated };
  if (!key) return null;
  if (domain && (expected.includes(domain) || companyDomain(input.company, [`https://${domain}`]))) return { kind: "logo-dev", src: logoDevUrl(domain, key) };
  // Audited map names retain coverage unless a known collision requires structured proof.
  if (!domain && mapped && qualified) return { kind: "logo-dev", src: logoDevUrl(mapped, key) };
  return null;
}

/** Next.js inlines NEXT_PUBLIC_* at build time; the pk_ key is publishable by design (docs.logo.dev). */
export const logoDevKey = process.env.NEXT_PUBLIC_LOGO_DEV_KEY ?? "";
