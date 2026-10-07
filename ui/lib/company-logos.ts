import domainsJson from "./company-logo-domains.json";
import catalogJson from "./company-logo-catalog.json";
import identitiesJson from "./company-logo-identities.json";
import { companyLogoOverrides, type CompanyLogoOverride } from "./company-logo-overrides";

export type CompanyLogoDomainMap = Readonly<Record<string, string | null>>;
const domains: CompanyLogoDomainMap = domainsJson;
const catalog = catalogJson as Record<string, string>;

export type CompanyLogoSource = { kind: "catalog" | "override" | "logo-dev"; src: string };
export type CompanyLogoInput = { company: string; applyUrl?: string | null; url?: string | null; rawJd?: string | null };
export type CompanyLogoIdentity = { domains: readonly string[]; unambiguous?: boolean };
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
  "builtin.com", "hibob.com", "gem.com", "dover.com", "jobs.ashbyhq.com", "google.com", "notion.site",
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

/** Explicit domains in job copy corroborate identity only when they resemble the employer or an identity pin. */
export function postingCompanyDomains(input: CompanyLogoInput, expected: readonly string[] = []): string[] {
  const references = input.rawJd?.match(/(?:https?:\/\/)?(?:[a-z0-9-]+\.)+[a-z]{2,}(?:\/[^\s<>"']*)?/gi) ?? [];
  const urls = [input.applyUrl, input.url, ...references.map(raw => /^https?:\/\//i.test(raw) ? raw : `https://${raw}`)];
  const found = new Set<string>();
  for (const [index, url] of urls.entries()) {
    if (!url) continue;
    try {
      const parsed = new URL(url);
      if (!["https:", "http:"].includes(parsed.protocol)) continue;
      const host = parsed.hostname.toLowerCase();
      if (sharedJobHosts.some(shared => host === shared || host.endsWith(`.${shared}`))) continue;
      const domain = registrableDomain(host);
      if (domain && (index < 2 || expected.includes(domain) || companyDomain(input.company, [url]))) found.add(domain);
    } catch { /* Invalid references provide no identity evidence. */ }
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
  const evidence = postingCompanyDomains(input, expected);
  // Two competing employer domains cannot be resolved by URL order or by a name match.
  if (evidence.length > 1) return null;
  const domain = evidence[0];
  const qualified = domain ? expected.includes(domain) : identity?.unambiguous === true && expected.every(candidate => identity.domains.includes(candidate));
  if (override?.kind === "file") return qualified ? { kind: "override", src: override.src } : null;
  if (override?.kind === "domain") return qualified && key ? { kind: "logo-dev", src: logoDevUrl(override.domain, key) } : null;
  const curated = own(catalog, name);
  if (curated && identity && qualified) return { kind: "catalog", src: curated };
  if (!key) return null;
  if (domain && (expected.includes(domain) || companyDomain(input.company, [`https://${domain}`]))) return { kind: "logo-dev", src: logoDevUrl(domain, key) };
  // An explicit unambiguous ruling is required even for a previously audited domain map.
  if (!domain && mapped && identity?.unambiguous && identity.domains.includes(mapped)) return { kind: "logo-dev", src: logoDevUrl(mapped, key) };
  return null;
}

/** Next.js inlines NEXT_PUBLIC_* at build time; the pk_ key is publishable by design (docs.logo.dev). */
export const logoDevKey = process.env.NEXT_PUBLIC_LOGO_DEV_KEY ?? "";
