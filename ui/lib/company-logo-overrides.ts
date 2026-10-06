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
  // These employer names resolve to unrelated Logo.dev brands. Keep initials until a correct mark
  // is verified, then pin a curated file or the employer domain.
  // Yael Adventures is an unrelated popular name match for these employers.
  "yael korentec technologies": { kind: "initials" },
  "yael group": { kind: "initials" },
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
