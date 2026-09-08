import catalogJson from "./company-logo-catalog.json";

const catalog = catalogJson as Record<string, string>;

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
