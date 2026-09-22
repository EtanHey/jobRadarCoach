// Isolated, credential-free app for the headless browser test. Never deploy it.
import { cp, mkdir, symlink, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { dirname, relative, resolve } from "node:path";
import assert from "node:assert/strict";
import "./build-map-worker.mjs";
const ui = fileURLToPath(new URL("..", import.meta.url));
const output = process.env.GLOBE_QA_OUTPUT;
assert.ok(output, "Set GLOBE_QA_OUTPUT to a fresh durable evidence directory");
const target = resolve(output, "fixture-app");
await mkdir(target, {recursive:true});
for (const name of ["app", "components", "lib", "public", "package.json", "tsconfig.json", "postcss.config.mjs", "next-env.d.ts"]) {
  await cp(resolve(ui,name),resolve(target,name),{recursive:true});
}
try { await symlink(resolve(ui,"node_modules"),resolve(target,"node_modules"),"dir"); } catch(error) { if(error.code!=="EEXIST") throw error; }
// Both the fixture and symlinked dependencies must be inside Turbopack's root.
let root = ui;
while (relative(root,target).startsWith("..")) root = dirname(root);
await writeFile(resolve(target,"next.config.ts"), `export default { turbopack: { root: ${JSON.stringify(root)} }, devIndicators: false };\n`);
await writeFile(resolve(target,"app/page.tsx"), 'import { JobBoard } from "@/components/job-board"; export default function Page() { return <JobBoard /> }');
console.log(target);
