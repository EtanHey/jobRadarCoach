// Pins for names the Logo.dev lookup gets wrong. Keys are canonicalCompanyName() output.
// "initials" shows the initials tile, "file" serves a curated /public asset, "domain" forces a Logo.dev domain lookup.
export type CompanyLogoOverride =
  | { kind: "initials" }
  | { kind: "file"; src: string }
  | { kind: "domain"; domain: string };

export const companyLogoOverrides: Readonly<Record<string, CompanyLogoOverride>> = {
  // Placeholder employers: a name lookup would return some unrelated brand.
  "confidential": { kind: "initials" },
  "confidential company": { kind: "initials" },
  "stealth": { kind: "initials" },
  "stealth startup": { kind: "initials" },
  "stealth mode startup": { kind: "initials" },
  "stealth mode": { kind: "initials" },
  "undisclosed": { kind: "initials" },
  // Wrong Logo.dev name-lookup images found in the 2026-10-04 eyeball review of the top companies
  // (docs.local/qa/2026-10-04-logo-eyeball). Pin a curated file or a domain instead once a correct mark is verified.
  "travelfactory lab": { kind: "initials" },
  "saic": { kind: "initials" },
  "ashley digital": { kind: "initials" },
  "qed science": { kind: "initials" },
  "deepl": { kind: "initials" },
  "extreme": { kind: "initials" },
  "solo clash": { kind: "initials" },
  "ergo next insurance": { kind: "initials" },
  "lovapex tech": { kind: "initials" },
};
