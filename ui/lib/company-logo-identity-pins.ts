import type { CompanyLogoIdentity } from "./company-logos";

// Reviewed employer identity pins; regenerate bindings after changes (docs/company-logo-identity-pins.md).
export const companyLogoIdentityPins: Record<string, CompanyLogoIdentity> = {
  doit: { domains: ["doit.com"], collision: true, sourceCompanies: ["linkedin:doitintl", "greenhouse:doitintl"] },
  "moveo group": { domains: ["moveo.group"] },
  "pagaya israel": { domains: ["pagaya.com"] },
  "real dev inc": { domains: ["real.dev"] },
  shifters: { domains: ["shiftersai.com"] },
  "tomax think academy": { domains: ["tomax.io"] },
  wix: { domains: ["wix.com"] },
};
