import assert from "node:assert/strict";
import { mkdtempSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { confidentDomain, refreshDomains, ownsDomain } from "../../scripts/refresh-logo-domains";

test("refresh accepts only exact canonical brand names or domain labels", () => {
  assert.equal(confidentDomain("Acme Robotics", [{ name: " ＡＣＭＥ\t Robotics ", domain: "acme.ai" }]), "acme.ai");
  assert.equal(confidentDomain("AgileGrid", [{ name: "Unrelated", domain: "agilegrid.com" }]), "agilegrid.com");
  assert.equal(confidentDomain("Yael Korentec Technologies", [{ name: "Yael Adventures", domain: "yaeladventures.com" }]), null);
  for (const domain of ["https://acme.com", "acme.com/path", "acme.com?token=secret", "acme.com:443", "-acme.com", "localhost", "127.0.0.1"]) {
    assert.equal(confidentDomain("Acme", [{ name: "Acme", domain }]), null, domain);
  }
});

test("refresh queries unseen names once, keeps null decisions, throttles and discards provider URLs", async () => {
  const requests: { url: URL; init?: RequestInit }[] = [], waits: number[] = [];
  const fetcher = (input: string | URL | Request, init?: RequestInit) => {
    requests.push({ url: new URL(String(input)), init });
    return Promise.resolve(new Response(JSON.stringify([{ name: "New Brand", domain: "newbrand.com", logo_url: "https://img.logo.dev/x?token=NEVER_PERSIST" }])));
  };
  const existing = { known: "known.com", rejected: null };
  const output = await refreshDomains(["KNOWN", "Rejected", " New Brand ", "new brand", "Unmatched", ""], existing, "sk_synthetic", fetcher as typeof fetch, ms => { waits.push(ms); return Promise.resolve(); });
  assert.deepEqual({ ...output }, { ...existing, "new brand": "newbrand.com", unmatched: null });
  assert.equal(requests.length, 2);
  assert.deepEqual(waits, [1000]);
  assert.deepEqual(existing, { known: "known.com", rejected: null });
  for (const { url, init } of requests) {
    assert.equal(url.origin, "https://api.logo.dev");
    assert.equal(url.pathname, "/search");
    assert.equal(url.searchParams.get("strategy"), "match");
    assert.equal(new Headers(init?.headers).get("authorization"), "Bearer sk_synthetic");
    assert.equal(init?.redirect, "error");
  }
  assert.doesNotMatch(JSON.stringify(output), /NEVER_PERSIST|sk_synthetic/);
});

test("refresh errors preserve decisions and never include credentials or provider bodies", async () => {
  const fetcher = () => Promise.resolve(new Response("sk_synthetic provider body", { status: 429 }));
  await assert.rejects(refreshDomains(["Acme"], {}, "sk_synthetic", fetcher as typeof fetch), /^Error: Brand Search failed \(HTTP 429\)$/);
  const malformed = () => Promise.resolve(new Response(JSON.stringify({ error: "sk_synthetic" })));
  await assert.rejects(refreshDomains(["Acme"], {}, "sk_synthetic", malformed as typeof fetch), /Invalid Brand Search response/);
});

test("transport errors and invalid JSON are sanitized without credentials", async () => {
  const network = () => Promise.reject(new Error("request sk_synthetic"));
  await assert.rejects(refreshDomains(["Acme"], {}, "sk_synthetic", network as typeof fetch), /^Error: Brand Search request failed$/);
  const invalid = () => Promise.resolve(new Response("sk_synthetic invalid JSON"));
  await assert.rejects(refreshDomains(["Acme"], {}, "sk_synthetic", invalid as typeof fetch), /^Error: Invalid Brand Search response$/);
});


test("CLI preserves known/null decisions without a provider request and fails safely on invalid input", () => {
  const directory = mkdtempSync(join(tmpdir(), "jrc-logo-refresh-"));
  try {
    const input = join(directory, "names.json"), output = join(directory, "map.json");
    writeFileSync(input, JSON.stringify(["KNOWN", "Rejected", "known"]));
    writeFileSync(output, JSON.stringify({ known: "known.com", rejected: null }));
    const args = ["--import", "tsx", fileURLToPath(new URL("../../scripts/refresh-logo-domains.ts", import.meta.url)), input, output];
    const run = () => spawnSync(process.execPath, args, { encoding: "utf8", env: { ...process.env, LOGO_DEV_SECRET_KEY: "sk_synthetic" }, timeout: 2000 });
    const success = run();
    assert.equal(success.status, 0, success.stderr);
    assert.deepEqual(JSON.parse(readFileSync(output, "utf8")), { known: "known.com", rejected: null });
    assert.match(success.stdout, /Domain map saved/);
    const before = readFileSync(output, "utf8");
    writeFileSync(input, "sk_synthetic malformed");
    const failure = run();
    assert.equal(failure.status, 1);
    assert.doesNotMatch(failure.stdout + failure.stderr, /sk_synthetic/);
    assert.equal(readFileSync(output, "utf8"), before);
  } finally { rmSync(directory, { recursive: true, force: true }); }
});

test("malformed candidates are provider errors, not permanent low-confidence decisions", async () => {
  for (const candidate of [null, {}, "not a candidate", { name: 7, domain: "acme.com" }, { name: "Acme", domain: 7 }]) {
    const fetcher = () => Promise.resolve(new Response(JSON.stringify([candidate])));
    await assert.rejects(refreshDomains(["Acme"], {}, "sk_synthetic", fetcher as typeof fetch), /^Error: Invalid Brand Search response$/);
  }
  const empty = () => Promise.resolve(new Response("[]"));
  assert.deepEqual(await refreshDomains(["Acme"], {}, "sk_synthetic", empty as typeof fetch), { acme: null });
});

for (const [company, domain] of [
  ["Johnson & Johnson MedTech", "vwavemedical.com"], ["Xpend", "cleanico.co.bw"],
  ["Amazon Web Services (AWS)", "buildonasean2021.com"], ["Unavailable", "autenticalamichoacana.com"],
]) {
  test(`matching candidate name cannot admit unrelated domain ${domain}`, () => {
    assert.equal(confidentDomain(company, [{ name: company, domain }]), null);
  });
}


test("ownership resemblance preserves verified abbreviations and distinctive tokens", () => {
  for (const [company, domain] of [
    ["General Motors", "gm.com"], ["General Dynamics Information Technology", "gdit.com"],
    ["Warner Music Group", "wmg.com"], ["Mentee Robotics", "menteebot.com"],
    ["Javelin Venture Partners", "javelinvp.com"], ["Connecteam", "connecteam.com"],
    ["Jeen.ai", "jeen.ai"], ["Bluebird Aero Systems", "bluebird-uav.com"],
    ["Bank of Jerusalem", "bankjerusalem.co.il"],
  ]) {
    assert.ok(ownsDomain(company, domain), company);
    assert.equal(confidentDomain(company, [{ name: company, domain }]), domain, company);
  }
  assert.ok(ownsDomain("Acme Technologies", "acmeportal.com"), "core token is contained in the domain label");
  assert.ok(ownsDomain("Acme Robotics", "acme.com"), "domain label is contained in joined company tokens");
  assert.ok(ownsDomain("World of Widgets", "ww.com"), "initials may omit of/and/the");
  assert.equal(ownsDomain("Acme", "a.com"), false, "one-character labels are ambiguous");
  assert.equal(ownsDomain("", "acme.com"), false);
  assert.equal(ownsDomain("Acme", "acme.com/path"), false);
});
