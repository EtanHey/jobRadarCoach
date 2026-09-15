import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { dirname, extname, resolve } from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";

const uiRoot = resolve(import.meta.dirname, "..");
const componentsRoot = resolve(uiRoot, "components");

function localImports(path: string): string[] {
  const source = readFileSync(path, "utf8");
  const imports = [
    ...[...source.matchAll(/(?:import|export)\s+(?:type\s+)?(?:[^"']*?\s+from\s+)?["']([^"']+)["']/g)].map((match) => match[1]),
    ...[...source.matchAll(/(?:import|require)\s*\(\s*["']([^"']+)["']\s*\)/g)].map((match) => match[1]),
  ];
  return imports.filter((specifier) => specifier.startsWith(".") || specifier.startsWith("@/"));
}

function resolveModule(from: string, specifier: string): string | null {
  const base = specifier.startsWith("@/")
    ? resolve(uiRoot, specifier.slice("@/".length))
    : resolve(dirname(from), specifier);
  for (const candidate of extname(base) ? [base] : [`${base}.ts`, `${base}.tsx`, resolve(base, "index.ts"), resolve(base, "index.tsx")]) {
    try {
      readFileSync(candidate);
      return candidate;
    } catch {}
  }
  return null;
}

function drawerModuleGraph(): string[] {
  const pending = [resolve(componentsRoot, "job-drawer.tsx")];
  const visited = new Set<string>();
  while (pending.length > 0) {
    const path = pending.pop()!;
    if (visited.has(path)) continue;
    visited.add(path);
    for (const specifier of localImports(path)) {
      const dependency = resolveModule(path, specifier);
      if (dependency) pending.push(dependency);
    }
  }
  return [...visited];
}

test("drawer import graph is host-portable and display-only", () => {
  const graph = drawerModuleGraph();
  for (const path of graph) {
    const source = readFileSync(path, "utf8");
    assert.doesNotMatch(source, /(?:from\s+|import\s+|(?:import|require)\s*\(\s*)["']next(?:\/|["'])/, path);
    assert.doesNotMatch(source, /\bfetch\s*\(/, path);
  }
  const drawerSource = readFileSync(resolve(componentsRoot, "job-drawer.tsx"), "utf8");
  assert.doesNotMatch(drawerSource, /status-select|\bchangeStatus\b|\bsaving\b/);
});

test("drawer renders host-provided actions and renders none when omitted", () => {
  const drawerUrl = pathToFileURL(resolve(componentsRoot, "job-drawer.tsx")).href;
  const probe = spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "--eval", `
    import React from "react";
    import * as drawerModule from ${JSON.stringify(drawerUrl)};
    const JobDrawer = drawerModule.JobDrawer ?? drawerModule.default?.JobDrawer;
    function text(node) {
      if (typeof node === "string" || typeof node === "number") return String(node);
      if (Array.isArray(node)) return node.map(text).join("");
      if (node && typeof node === "object" && "props" in node) return text(node.props.children);
      return "";
    }
    function countElements(node, type) {
      if (Array.isArray(node)) return node.reduce((sum, child) => sum + countElements(child, type), 0);
      if (!node || typeof node !== "object" || !("props" in node)) return 0;
      return Number(node.type === type) + countElements(node.props.children, type);
    }
    const base = { selected: null, detail: null, detailError: "", openerRef: { current: null }, retryDetail() {}, selectJob() {} };
    const loaded = { id: "12345678-1234-4234-8234-123456789abc", title: "Role", company: "Example", location: null, remote: null, experience: null, description_available: false, seniority: null, stack: [], raw_jd: null };
    const withActions = JobDrawer({ ...base, actions: React.createElement("span", null, "Host action sentinel") });
    const withoutActions = JobDrawer(base);
    const loadedWithoutActions = JobDrawer({ ...base, detail: loaded, selected: loaded.id });
    process.stdout.write(JSON.stringify({
      withActions: text(withActions),
      withActionsFooters: countElements(withActions, "footer"),
      withoutActions: text(withoutActions),
      withoutActionsFooters: countElements(withoutActions, "footer"),
      loadedWithoutActionsFooters: countElements(loadedWithoutActions, "footer"),
    }));
  `], { cwd: uiRoot, encoding: "utf8" });

  assert.equal(probe.status, 0, probe.stderr);
  const rendered = JSON.parse(probe.stdout) as { withActions: string; withActionsFooters: number; withoutActions: string; withoutActionsFooters: number; loadedWithoutActionsFooters: number };
  assert.match(rendered.withActions, /Host action sentinel/);
  assert.equal(rendered.withActionsFooters, 1);
  assert.doesNotMatch(rendered.withoutActions, /Host action sentinel/);
  assert.equal(rendered.withoutActionsFooters, 0);
  assert.equal(rendered.loadedWithoutActionsFooters, 0);
});
