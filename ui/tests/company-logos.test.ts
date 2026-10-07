import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";
import { canonicalCompanyName, companyDomain, companyInitials, resolveCompanyLogo } from "../lib/company-logos";
import catalog from "../lib/company-logo-catalog.json";
import { companyLogoOverrides } from "../lib/company-logo-overrides";

const logoPathForCompany = (company: string): string | null => (catalog as Record<string, string>)[canonicalCompanyName(company)] ?? null;


test("company names canonicalize without guessing corporate aliases", () => {
  assert.equal(canonicalCompanyName("  ACME\t Labs  "), "acme labs");
  assert.notEqual(canonicalCompanyName("Acme, Inc."), canonicalCompanyName("Acme"));
});

test("catalog resolves captured names and leaves unknown identities explicit", () => {
  assert.match(logoPathForCompany("MeeBoss") ?? "", /^\/companies\/meeboss-[a-f0-9]{10}\.(?:jpg|png|gif|webp)$/);
  assert.equal(logoPathForCompany("Definitely Not A Captured Company"), null);
});

test("verified official logos resolve with matching raster assets and provenance", () => {
  const manifest = JSON.parse(readFileSync(new URL("../public/companies/manifest.json", import.meta.url), "utf8"));
  for (const company of ["Pagaya Israel", "REAL DEV INC", "Shifters", "Tomax Think Academy", "Wix", "Moveo Group"]) {
    const entry = manifest.entries.find((item: { canonicalName: string }) => item.canonicalName === canonicalCompanyName(company));
    assert.ok(entry, `${company} is represented in the manifest`);
    assert.equal(entry.source.kind, "official-company-site");
    assert.equal(logoPathForCompany(company), `/companies/${entry.file}`);
    const bytes = readFileSync(new URL(`../public/companies/${entry.file}`, import.meta.url));
    assert.deepEqual([...bytes.subarray(0, 8)], [137, 80, 78, 71, 13, 10, 26, 10]);
    assert.equal(createHash("sha256").update(bytes).digest("hex"), entry.sha256);
  }
});

test("fallback initials support words and non-Latin names", () => {
  assert.equal(companyInitials("Blue Vine"), "BV");
  assert.equal(companyInitials("אביב טכנולוגיות"), "אט");
  assert.equal(companyInitials("---"), "?");
});

const KEY = "pk_test_publishable";
const logoDev = (src: string | undefined): URL => {
  assert.ok(src, "expected a Logo.dev URL");
  return new URL(src);
};

test("Doit app evidence never inherits the DoiT International catalog mark", () => {
  const input = { company: "Doit", applyUrl: "https://doit.app/careers/1" };
  assert.equal(resolveCompanyLogo(input), null);
  assert.equal(logoDev(resolveCompanyLogo(input, { logoDevKey: KEY })?.src).pathname, "/doit.app");
});

test("DoiT com evidence retains its curated logo, but a name alone does not", () => {
  assert.deepEqual(resolveCompanyLogo({ company: "DoiT", applyUrl: "https://careers.doit.com/jobs/1" }),
    { kind: "catalog", src: logoPathForCompany("DoiT") });
  assert.equal(resolveCompanyLogo({ company: "Doit", url: "https://www.linkedin.com/jobs/view/1" }, { logoDevKey: KEY }), null);
});

test("conflicting company domains veto both catalog and domain lookup", () => {
  assert.equal(resolveCompanyLogo({ company: "Doit", applyUrl: "https://doit.com/jobs/1", url: "https://doit.app/jobs/1" }, { logoDevKey: KEY }), null);
  assert.equal(resolveCompanyLogo({ company: "Doit", applyUrl: "https://doit.com/jobs/1", rawJd: "Our partner is at https://doit.app." }, { logoDevKey: KEY })?.kind, "catalog");
});

test("ordinary catalog and audited mapped names retain coverage without conflicting identity", () => {
  assert.equal(resolveCompanyLogo({ company: "MeeBoss" }, { logoDevKey: KEY })?.kind, "catalog");
  assert.equal(logoDev(resolveCompanyLogo({ company: "Acme Robotics" }, { logoDevKey: KEY, domainMap: { "acme robotics": "acmerobotics.ai" } })?.src).pathname, "/acmerobotics.ai");
  assert.equal(resolveCompanyLogo({ company: "Unseen Widgets" }, { logoDevKey: KEY, domainMap: {} }), null);
});

test("curated catalog wins over Logo.dev even when a key and a company domain exist", () => {
  const resolved = resolveCompanyLogo({ company: "Wix", applyUrl: "https://careers.wix.com/jobs/1" }, { logoDevKey: KEY });
  assert.deepEqual(resolved, { kind: "catalog", src: logoPathForCompany("Wix") });
});

test("without a publishable key nothing resolves to Logo.dev", () => {
  assert.equal(resolveCompanyLogo({ company: "Acme Robotics", applyUrl: "https://acmerobotics.com/careers/1" }, {}), null);
  assert.equal(resolveCompanyLogo({ company: "Acme Robotics" }, { logoDevKey: "" }), null);
  // A secret key must never be shipped to the browser, so anything that is not pk_ is ignored.
  assert.equal(resolveCompanyLogo({ company: "Acme Robotics" }, { logoDevKey: "sk_live_secret" }), null);
});

test("a trustworthy company-site apply URL resolves Logo.dev by registrable domain", () => {
  const resolved = resolveCompanyLogo({ company: "Acme Robotics", applyUrl: "https://careers.acme.co.il/jobs/42", url: "https://www.linkedin.com/jobs/view/1" }, { logoDevKey: KEY });
  assert.equal(resolved?.kind, "logo-dev");
  const url = logoDev(resolved?.src);
  assert.equal(url.origin, "https://img.logo.dev");
  assert.equal(url.pathname, "/acme.co.il");
  assert.equal(url.searchParams.get("token"), KEY);
  assert.equal(url.searchParams.get("fallback"), "404");
  assert.equal(url.searchParams.get("size"), "128");
});

test("ATS and job-board hosts are never used as the company domain", () => {
  const hosts = [
    "https://job-boards.greenhouse.io/acme/jobs/1", "https://boards.eu.greenhouse.io/acme/jobs/1", "https://jobs.lever.co/acme/1",
    "https://jobs.ashbyhq.com/acme/1", "https://apply.workable.com/acme/j/1", "https://www.comeet.com/jobs/acme/1",
    "https://jobs.smartrecruiters.com/Acme/1", "https://acme.wd5.myworkdayjobs.com/en-US/1", "https://www.linkedin.com/jobs/view/1",
    "https://acme.bamboohr.com/careers/1", "https://acme.recruitee.com/o/1",
  ];
  for (const applyUrl of hosts) {
    assert.equal(resolveCompanyLogo({ company: "Acme", applyUrl, url: applyUrl }, { logoDevKey: KEY }), null, applyUrl);
  }
});

test("a host that does not match the company name renders initials", () => {
  assert.equal(resolveCompanyLogo({ company: "Acme Robotics", applyUrl: "https://jobs.some-aggregator.com/acme/1" }, { logoDevKey: KEY }), null);
});

test("company domains need the company's own name in the registrable label", () => {
  assert.equal(companyDomain("Pagaya Israel", ["https://careers.pagaya.com/x"]), "pagaya.com");
  assert.equal(companyDomain("Moveo Group", ["https://www.moveo-group.com/jobs"]), "moveo-group.com");
  assert.equal(companyDomain("monday.com", ["https://monday.com/careers/1"]), "monday.com");
  assert.equal(companyDomain("Acme", ["https://www.example.com/acme"]), null);
  assert.equal(companyDomain("Acme", ["not a url", null, undefined]), null);
  assert.equal(companyDomain("Acme", ["http://localhost/acme", "https://10.0.0.1/acme"]), null);
});

test("override map pins a bad match to initials, a curated file, or a known domain", () => {
  const overrides = {
    "acme": { kind: "initials" },
    "beta labs": { kind: "file", src: "/companies/wix-295a1f6f92.png" },
    "gamma": { kind: "domain", domain: "gamma.app" },
  } as const;
  assert.equal(resolveCompanyLogo({ company: " ACME " }, { logoDevKey: KEY, overrides }), null);
  assert.deepEqual(resolveCompanyLogo({ company: "Beta Labs", applyUrl: "https://beta.example/jobs/1" }, { logoDevKey: KEY, overrides, identities: { "beta labs": { domains: ["beta.example"] } } }), { kind: "override", src: "/companies/wix-295a1f6f92.png" });
  assert.equal(logoDev(resolveCompanyLogo({ company: "Gamma", applyUrl: "https://gamma.app/jobs/1" }, { logoDevKey: KEY, overrides })?.src).pathname, "/gamma.app");
  assert.equal(resolveCompanyLogo({ company: "Gamma", applyUrl: "https://gamma.app/jobs/1" }, { overrides }), null, "a domain pin still needs the key");
});

test("placeholder employer names never hit a name lookup", () => {
  for (const company of ["Confidential", "Stealth Startup", "Stealth Mode Startup", "Undisclosed"]) {
    assert.equal(resolveCompanyLogo({ company }, { logoDevKey: KEY }), null, company);
  }
});

test("a domain override beats the curated catalog, and without a key it pins to initials", () => {
  const overrides = { wix: { kind: "domain", domain: "wix.example" } } as const;
  assert.equal(logoDev(resolveCompanyLogo({ company: "Wix", applyUrl: "https://wix.example/jobs/1" }, { logoDevKey: KEY, overrides })?.src).pathname, "/wix.example");
  assert.equal(resolveCompanyLogo({ company: "Wix" }, { overrides }), null, "a wrong catalog mark must not come back when the key is missing");
});

test("a generic word that merely prefixes the company name is not its domain", () => {
  assert.equal(companyDomain("TechGym", ["https://tech.com/careers"]), null);
  assert.equal(companyDomain("Labster", ["https://labs.com/careers"]), null);
  assert.equal(companyDomain("TechGym", ["https://techgym.co.il/careers"]), "techgym.co.il");
});

test("every initials pin in the shipped override map beats Logo.dev and the catalog", () => {
  const pins = Object.entries(companyLogoOverrides).filter(([, pin]) => pin.kind === "initials");
  // 7 placeholder employers plus the 9 wrong name matches from the 2026-10-04 eyeball review.
  assert.ok(pins.length >= 16, `expected at least 16 initials pins, found ${pins.length}`);
  for (const [name] of pins) {
    assert.equal(name, canonicalCompanyName(name), `${name} is stored in canonical form`);
    assert.equal(resolveCompanyLogo({ company: name.toUpperCase() }, { logoDevKey: KEY }), null, name);
  }
});

test("corroborated domain map shares canonical matching", () => {
  const domainMap = { "acme robotics": "acmerobotics.ai" };
  const resolved = resolveCompanyLogo({ company: "  ＡＣＭＥ\t Robotics ", applyUrl: "https://acmerobotics.ai/jobs/1" }, { logoDevKey: KEY, domainMap });
  const url = logoDev(resolved?.src);
  assert.equal(url.pathname, "/acmerobotics.ai");
  assert.equal(url.searchParams.get("size"), "128");
  assert.equal(url.searchParams.get("format"), "png");
  assert.equal(url.searchParams.get("theme"), "light");
  assert.equal(url.searchParams.get("fallback"), "404");
});

test("mapped null and absent companies both need posting identity", () => {
  const options = { logoDevKey: KEY, domainMap: { "acme robotics": null } };
  assert.equal(resolveCompanyLogo({ company: "ACME Robotics" }, options), null);
  assert.equal(resolveCompanyLogo({ company: "Unseen Widgets" }, options), null);
});

test("override, catalog and trusted apply domain precede the domain map", () => {
  const domainMap = { wix: null, "acme robotics": "acmerobotics.ai", saic: "saic.com" };
  assert.equal(resolveCompanyLogo({ company: "SAIC" }, { logoDevKey: KEY, domainMap }), null);
  assert.equal(resolveCompanyLogo({ company: "Wix" }, { logoDevKey: KEY, domainMap })?.kind, "catalog");
  assert.equal(logoDev(resolveCompanyLogo({ company: "Acme Robotics", applyUrl: "https://acmerobotics.com/jobs" }, { logoDevKey: KEY, domainMap })?.src).pathname, "/acmerobotics.com");
  assert.equal(resolveCompanyLogo({ company: "Acme Robotics" }, { domainMap }), null);
});

test("both Yael employers stay initials even with a mapped or apply domain", () => {
  for (const company of ["Yael Korentec Technologies", "Yael Group"]) {
    assert.equal(resolveCompanyLogo({ company, applyUrl: "https://yael.com/jobs" }, {
      logoDevKey: KEY, domainMap: { [canonicalCompanyName(company)]: "yaeladventures.com" },
    }), null, company);
  }
});

test("the committed domain map contains canonical keys and only safe domains or explicit null", async () => {
  const { validLogoDomain } = await import("../../scripts/refresh-logo-domains");
  const map = JSON.parse(readFileSync(new URL("../lib/company-logo-domains.json", import.meta.url), "utf8"));
  assert.ok(map && !Array.isArray(map) && typeof map === "object");
  for (const [name, domain] of Object.entries(map)) {
    assert.equal(name, canonicalCompanyName(name));
    assert.ok(name.length > 0);
    assert.ok(domain === null || validLogoDomain(domain), name);
  }
});

test("the shipped map resolves Jeen.ai by domain and TalentHop to initials", () => {
  assert.equal(logoDev(resolveCompanyLogo({ company: "JEEN.AI" }, { logoDevKey: KEY })?.src).pathname, "/jeen.ai");
  assert.equal(resolveCompanyLogo({ company: "TalentHop" }, { logoDevKey: KEY }), null);
  assert.equal(resolveCompanyLogo({ company: "Alice (Formerly ActiveFence)" }, { logoDevKey: KEY }), null);
  assert.equal(resolveCompanyLogo({ company: "Yael Group" }, { logoDevKey: KEY }), null);
});

test("AWS never uses the supplied event-specific domain without verified artwork", () => {
  assert.equal(resolveCompanyLogo({ company: "Amazon Web Services (AWS)" }, { logoDevKey: KEY }), null);
});

test("Unavailable is an unknown employer, not the supplied ice-cream brand", () => {
  assert.equal(resolveCompanyLogo({ company: "Unavailable" }, { logoDevKey: KEY }), null);
});


test("lead ownership ruling drops two unrelated brands from the shipped map", () => {
  for (const company of ["Johnson & Johnson MedTech", "Xpend"]) {
    assert.equal(resolveCompanyLogo({ company }, { logoDevKey: KEY }), null, company);
  }
});

test("Opus-reviewed homonyms and suspect brands resolve to initials", () => {
  const companies = [
    "Siemens EDA (Siemens Digital Industries Software)", "Roark (YC W25)", "DRW",
    "Minute", "DT", "Dialog", "Medulla", "Venn", "Nimble",
    "ACT", "OP", "Neo", "ELTA Systems Ltd", "Mylo AI", "Yara AI", "Ocho",
  ];
  assert.deepEqual(
    companies.map((company) => resolveCompanyLogo({ company }, { logoDevKey: KEY })),
    companies.map(() => null),
  );
});

test("UTF-8 company names match the shipped map instead of falling through to name lookup", () => {
  const map = JSON.parse(readFileSync(new URL("../lib/company-logo-domains.json", import.meta.url), "utf8"));
  for (const company of ["Bank of Jerusalem בנק ירושלים", "Discount Bank בנק דיסקונט", "Goldjobs מבינים באנשים", "Ness Technologies | נס טכנולוגיות", "Plus500™", "SWAKIO™"]) {
    assert.ok(Object.hasOwn(map, canonicalCompanyName(company)), company);
    const resolved = resolveCompanyLogo({ company }, { logoDevKey: KEY });
    if (resolved?.kind === "logo-dev") assert.ok(!logoDev(resolved.src).pathname.startsWith("/name/"), company);
  }
});

test("explicit unambiguous exceptions cannot override conflicting evidence", () => {
  assert.equal(resolveCompanyLogo({ company: "Wix", rawJd: "Our partner uses wix.app." })?.kind, "catalog");
  assert.equal(logoDev(resolveCompanyLogo({ company: "Jeen.ai", applyUrl: "https://jeen.app/jobs/1" }, { logoDevKey: KEY })?.src).pathname, "/jeen.app");
});

test("a map cannot substitute another homonym domain for posting evidence", () => {
  const domainMap = { doit: "doit.com" };
  assert.equal(logoDev(resolveCompanyLogo({ company: "Doit", applyUrl: "https://doit.app/jobs/1" }, { logoDevKey: KEY, domainMap })?.src).pathname, "/doit.app");
});

test("free-text partner, negation, email and userinfo mentions never grant identity", () => {
  for (const rawJd of ["Our cloud partner is DoiT (https://doit.com).", "We are not affiliated with doit.com.", "Contact support@doit.com.", "See https://doit.com@attacker.example/jobs/1"]) {
    assert.equal(resolveCompanyLogo({ company: "Doit", url: "https://www.linkedin.com/jobs/view/1", rawJd }, { logoDevKey: KEY }), null, rawJd);
    assert.equal(resolveCompanyLogo({ company: "Wix", applyUrl: "https://wix.com/jobs/1", rawJd })?.kind, "catalog", rawJd);
  }
});

test("DoiT structured ATS/company and verified posting bindings retain its catalog", () => {
  for (const input of [
    { company: "DoiT", applyUrl: "https://boards.greenhouse.io/doitintl/jobs/1" },
    { company: "DoiT", sourceCompany: "linkedin:doitintl" },
    { company: "DoiT", postingId: "799dfdd2-e6a0-43b0-9fbe-b30debbfde81" },
  ]) assert.equal(resolveCompanyLogo(input)?.kind, "catalog");
  assert.equal(resolveCompanyLogo({ company: "Doit", sourceCompany: "linkedin:doit-official" }), null);
  assert.equal(resolveCompanyLogo({ company: "Doit", postingId: "f0dc6b0d-5897-4e50-9946-5e91aae3e321" }), null);
  assert.equal(resolveCompanyLogo({ company: "DoiT", sourceCompany: "linkedin:doit-official", applyUrl: "https://doit.com/jobs/1" }), null);
});

test("prototype keys cannot select inherited logo entries", () => {
  for (const company of ["constructor", "toString", "__proto__"]) {
    assert.equal(resolveCompanyLogo({ company }, { logoDevKey: KEY }), null);
  }
});


test("unambiguous name exceptions and catalog pins reject unrelated posting hosts", () => {
  assert.equal(resolveCompanyLogo({ company: "Wix", applyUrl: "https://unrelated.example/jobs/1" }, { logoDevKey: KEY }), null);
  assert.equal(resolveCompanyLogo({ company: "Jeen.ai", applyUrl: "https://unrelated.example/jobs/1" }, { logoDevKey: KEY }), null);
  assert.equal(resolveCompanyLogo({ company: "Doit", applyUrl: "https://doit.com/jobs/1", url: "https://unrelated.example/jobs/1" }, { logoDevKey: KEY }), null);
});
