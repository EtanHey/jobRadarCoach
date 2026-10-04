import catalogJson from "./company-logo-catalog.json";
import { companyLogoOverrides, type CompanyLogoOverride } from "./company-logo-overrides";

const catalog = catalogJson as Record<string, string>;

export type CompanyLogoSource = { kind: "catalog" | "override" | "logo-dev"; src: string };
export type CompanyLogoInput = { company: string; applyUrl?: string | null; url?: string | null };
export type CompanyLogoOptions = { logoDevKey?: string; overrides?: Readonly<Record<string, CompanyLogoOverride>> };

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

export function logoPathForCompany(company: string): string | null {
  return catalog[canonicalCompanyName(company)] ?? null;
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
      || (flatLabel.length >= 4 && compact.startsWith(flatLabel))
      || words.some((word) => word.length >= 3 && !genericCompanyWords.has(word) && (word === label || word === flatLabel));
    if (named) return domain;
  }
  return null;
}

function logoDevUrl(path: string, key: string): string {
  const params = new URLSearchParams({ token: key, size: String(LOGO_DEV_SIZE), format: "png", theme: "light", fallback: "404" });
  return `https://img.logo.dev/${path}?${params}`;
}

/**
 * One resolution order for every logo in the app: override map, curated catalog, Logo.dev (domain, then name),
 * else null so the caller renders initials. Logo.dev only runs with a publishable (pk_) key.
 */
export function resolveCompanyLogo(input: CompanyLogoInput, options: CompanyLogoOptions = {}): CompanyLogoSource | null {
  const name = canonicalCompanyName(input.company);
  const key = options.logoDevKey?.startsWith("pk_") ? options.logoDevKey : null;
  const override = (options.overrides ?? companyLogoOverrides)[name];
  if (override?.kind === "initials") return null;
  if (override?.kind === "file") return { kind: "override", src: override.src };
  const curated = catalog[name];
  if (curated) return { kind: "catalog", src: curated };
  if (!key || !name) return null;
  if (override?.kind === "domain") return { kind: "logo-dev", src: logoDevUrl(override.domain, key) };
  const domain = companyDomain(input.company, [input.applyUrl, input.url]);
  return { kind: "logo-dev", src: logoDevUrl(domain ?? `name/${encodeURIComponent(input.company.trim())}`, key) };
}

/** Next.js inlines NEXT_PUBLIC_* at build time; the pk_ key is publishable by design (docs.logo.dev). */
export const logoDevKey = process.env.NEXT_PUBLIC_LOGO_DEV_KEY ?? "";
