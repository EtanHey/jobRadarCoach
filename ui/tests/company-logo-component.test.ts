import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";

const uiRoot = resolve(import.meta.dirname, "..");
const componentUrl = pathToFileURL(resolve(uiRoot, "components/company-logo.tsx")).href;

function render(props: Record<string, unknown>, env: Record<string, string> = {}, exportName = "CompanyLogo", storage?: Record<string, string>): string {
  const probe = spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "--eval", `
    ${storage ? `const data = new Map(Object.entries(${JSON.stringify(storage)}));
    globalThis.window = { localStorage: { getItem: key => data.get(key) ?? null, setItem: (key, value) => data.set(key, value) } };` : ""}
    import React from "react";
    import { renderToStaticMarkup } from "react-dom/server";
    const module = await import(${JSON.stringify(componentUrl)});
    const Component = module[${JSON.stringify(exportName)}] ?? module.default?.[${JSON.stringify(exportName)}];
    process.stdout.write(renderToStaticMarkup(React.createElement(Component, ${JSON.stringify(props)})));
  `], { cwd: uiRoot, encoding: "utf8", env: { ...process.env, NEXT_PUBLIC_LOGO_DEV_KEY: "", ...env } });
  assert.equal(probe.status, 0, probe.stderr);
  return probe.stdout;
}

test("unmapped companies render the initials tile without an image", () => {
  const html = render({ company: "Blue Vine" });
  assert.match(html, /data-logo-state="unmapped"/);
  assert.match(html, /aria-label="Blue Vine logo unavailable"/);
  assert.match(html, />BV</);
  assert.doesNotMatch(html, /<img/);
});

test("the Doit app posting renders initials instead of the DoiT image", () => {
  const html = render({ company: "Doit", applyUrl: "https://doit.app/careers/1" });
  assert.match(html, /data-logo-state="unmapped"/);
  assert.match(html, />D</);
  assert.doesNotMatch(html, /<img|doit-1a4c4090b4/);
});

test("catalog logos render on the shared neutral frame and stay hidden until loaded", () => {
  const html = render({ company: "Wix" });
  assert.match(html, /data-logo-source="catalog"/);
  assert.match(html, /data-logo-state="loading"/);
  assert.match(html, /<img[^>]+src="\/companies\/wix-[a-f0-9]{10}\.png"/);
  assert.match(html, /<img[^>]+class="[^"]*opacity-0/);
  assert.match(html, /<img[^>]+class="[^"]*object-contain/);
  assert.match(html, /<img[^>]+loading="lazy"/, "offscreen rail and grid cards must not fetch logos up front");
});

test("every size shares one frame and only the box size changes", () => {
  const frame = (html: string) => (html.match(/^<span data-company-logo[^>]+class="([^"]+)"/)?.[1] ?? "").split(" ").filter((name) => !name.startsWith("size-") && !name.startsWith("sm:size-") && !name.startsWith("text-")).sort();
  const sm = render({ company: "Wix", size: "sm" });
  const md = render({ company: "Wix" });
  assert.match(sm, /data-logo-size="sm"/);
  assert.match(md, /data-logo-size="md"/);
  assert.deepEqual(frame(sm), frame(md));
});

test("with a publishable key, unmapped companies ask Logo.dev and keep the initials fallback wiring", () => {
  const html = render({ company: "Acme Robotics", applyUrl: "https://careers.acmerobotics.com/1" }, { NEXT_PUBLIC_LOGO_DEV_KEY: "pk_component_test" });
  assert.match(html, /data-logo-source="logo-dev"/);
  assert.match(html, /<img[^>]+src="https:\/\/img\.logo\.dev\/acmerobotics\.com\?token=pk_component_test&amp;size=128&amp;format=png&amp;theme=light&amp;fallback=404"/);
});

test("card, drawer and globe rail all use the one shared CompanyLogo", () => {
  const source = (path: string) => readFileSync(resolve(uiRoot, path), "utf8");
  const drawer = source("components/job-drawer.tsx");
  assert.match(drawer, /import \{ CompanyLogo \} from "\.\/company-logo"/);
  assert.doesNotMatch(drawer, /<img|DrawerCompanyLogo|logoPathForCompany/);
  assert.match(source("components/job-card.tsx"), /<CompanyLogo company=\{job\.company\} applyUrl=\{job\.apply_url\} url=\{job\.url\} postingId=\{job\.id\} size=\{logoSize\}/);
  assert.match(source("components/job-cards.tsx"), /logoSize=\{sections \? "sm" : "md"\}/);
  assert.doesNotMatch(source("components/company-logo.tsx"), /from ["']next/);
});

test("Logo.dev attribution renders only when Logo.dev can serve logos, and keeps the referrer it verifies", () => {
  assert.equal(render({}, {}, "LogoDevAttribution"), "");
  const html = render({}, { NEXT_PUBLIC_LOGO_DEV_KEY: "pk_component_test" }, "LogoDevAttribution");
  assert.match(html, /<a[^>]+href="https:\/\/logo\.dev"[^>]*>Logos provided by Logo\.dev<\/a>/);
  assert.doesNotMatch(html, /noreferrer/);
  assert.match(html, /<a[^>]+target="_blank"[^>]+rel="noopener"/);
  assert.match(readFileSync(resolve(uiRoot, "components/job-board.tsx"), "utf8"), /<LogoDevAttribution \/>/);
});

test("a remembered Logo.dev miss renders initials at once and requests nothing", () => {
  const env = { NEXT_PUBLIC_LOGO_DEV_KEY: "pk_component_test" };
  const props = { company: "Acme Robotics", applyUrl: "https://careers.acmerobotics.com/1" };
  const miss = { "job-radar.logo-misses.v1": JSON.stringify({ "/acmerobotics.com": { at: Date.now(), strikes: 2 } }) };
  const html = render(props, env, "CompanyLogo", miss);
  assert.match(html, /data-logo-state="cached-miss"/);
  assert.match(html, /data-logo-source="logo-dev"/);
  assert.match(html, />AR</);
  assert.doesNotMatch(html, /<img|img\.logo\.dev/, "no request for a known miss");
  // Another company's miss does not affect this one, and an expired miss asks again.
  const other = { "job-radar.logo-misses.v1": JSON.stringify({ "/elsewhere.com": { at: Date.now(), strikes: 2 } }) };
  assert.match(render(props, env, "CompanyLogo", other), /<img[^>]+src="https:\/\/img\.logo\.dev\/acmerobotics\.com/);
  const expired = { "job-radar.logo-misses.v1": JSON.stringify({ "/acmerobotics.com": { at: Date.now() - 31 * 24 * 3600 * 1000, strikes: 2 } }) };
  assert.match(render(props, env, "CompanyLogo", expired), /<img[^>]+src="https:\/\/img\.logo\.dev\/acmerobotics\.com/);
});

test("a malformed miss-cache entry never breaks the logo render", () => {
  const env = { NEXT_PUBLIC_LOGO_DEV_KEY: "pk_component_test" };
  const props = { company: "Acme Robotics", applyUrl: "https://careers.acmerobotics.com/1" };
  for (const raw of [JSON.stringify({ "/acmerobotics.com": null }), JSON.stringify({ "/acmerobotics.com": { at: "x", strikes: [] } }), "[1]", "{broken"]) {
    const html = render(props, env, "CompanyLogo", { "job-radar.logo-misses.v1": raw });
    assert.match(html, /<img[^>]+src="https:\/\/img\.logo\.dev\/acmerobotics\.com/, raw);
  }
});
