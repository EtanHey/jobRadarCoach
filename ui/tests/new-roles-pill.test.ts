import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";

test("new roles pill names the refresh action", () => {
  const component = pathToFileURL(resolve(import.meta.dirname, "../components/new-roles-pill.tsx")).href;
  const probe = spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "--eval", `
    import { renderToStaticMarkup } from "react-dom/server";
    import * as module from ${JSON.stringify(component)};
    const Pill = module.NewRolesPill ?? module.default?.NewRolesPill;
    process.stdout.write(renderToStaticMarkup(Pill({ count: 3, truncated: false, onShow() {} })));
  `], { cwd: resolve(import.meta.dirname, ".."), encoding: "utf8" });
  assert.equal(probe.status, 0, probe.stderr);
  assert.match(probe.stdout, /aria-label="Show 3 new roles \(refreshes the list\)"/);
});
