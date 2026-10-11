// Real JobCards + lazy GlobeCard with the repository's hover/selection selectors.
import { build } from "esbuild";
import { chromium, expect } from "@playwright/test";
import { createServer } from "node:http";
import { readFile, writeFile, mkdir } from "node:fs/promises";
import assert from "node:assert/strict";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";
const output = process.env.GLOBE_QA_OUTPUT
  ? pathToFileURL(resolve(process.env.GLOBE_QA_OUTPUT) + "/")
  : new URL("../../docs.local/receipts/globe-card-hydration/", import.meta.url);
await mkdir(output, { recursive: true });
await build({ entryPoints: [new URL("fixtures/globe-card.tsx", import.meta.url).pathname], bundle: true,
  outfile: new URL("card.js", output).pathname, platform: "browser", format: "iife", jsx: "automatic",
  tsconfig: new URL("../tsconfig.json", import.meta.url).pathname,
  define: { "process.env.NODE_ENV": '"production"', "process.env": '{}'} });
const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");
const states = css.split("\n").filter(line => /^\[data-(hovered|globe-selected)/.test(line)).join("\n");
assert.ok(states.includes("box-shadow"), "must exercise the actual state rules");
const html = `<style>:root{--primary:rgb(0,100,240);--globe-select:rgb(200,0,200);--muted:rgb(220,220,220)}
body{font-family:Arial;margin:30px}article{border:1px solid grey;margin:20px 0;padding:20px}${states}</style>
<div id="app"></div><script src="/card.js"></script>`;
const server = createServer(async (req, res) => {
  res.setHeader("content-type", req.url === "/card.js" ? "application/javascript" : "text/html");
  res.end(req.url === "/card.js" ? await readFile(new URL("card.js", output)) : html);
});
await new Promise(resolve => server.listen(0, "127.0.0.1", resolve));
const browser = await chromium.launch({ headless: true });
try {
  const page = await browser.newPage({ viewport: { width: 900, height: 900 } });
  const errors = [];
  page.on("pageerror", error => errors.push(error.message));
  await page.goto(`http://127.0.0.1:${server.address().port}`);
  await expect(page.locator("article")).toHaveCount(2);
  const full = page.locator("[data-globe-card]").nth(0).locator("article");
  const lazy = page.locator("[data-globe-card]").nth(1).locator("article");
  assert.notEqual(await full.evaluate(el => getComputedStyle(el).boxShadow), "none");
  await lazy.getByRole("button", { name: /^Open / }).click();
  await expect(page.locator("[data-globe-card]").nth(1)).toHaveAttribute("data-globe-selected", "true");
  const selected = await lazy.evaluate(el => ({ shadow: getComputedStyle(el).boxShadow,
    directChild: el.matches("[data-globe-selected=true] > article") }));
  await page.locator("[data-globe-card]").nth(1).evaluate(el => {
    el.removeAttribute("data-globe-selected"); el.setAttribute("data-hovered", "");
  });
  const hovered = await lazy.evaluate(el => ({ matches: el.matches("[data-hovered] > article"),
    border: getComputedStyle(el).borderColor, background: getComputedStyle(el).backgroundImage }));
  await page.screenshot({ path: new URL("card.png", output).pathname });
  const receipt = { selected, hovered, idReads: await page.evaluate(() => window.fixtureReads()), errors };
  await writeFile(new URL("card.json", output), JSON.stringify(receipt, null, 2));
  console.log(JSON.stringify(receipt));
  assert.equal(selected.directChild, true);
  assert.notEqual(selected.shadow, "none");
  assert.equal(hovered.matches, true);
  assert.equal(hovered.border, "rgb(200, 0, 200)");
  assert.notEqual(hovered.background, "none");
  assert.equal(receipt.idReads, 1);
  assert.deepEqual(errors, []);
} finally { await browser.close(); await new Promise(resolve => server.close(resolve)); }
