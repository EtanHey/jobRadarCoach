import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";

test("LinkedIn closure badge labels its evidence link with the viewer's checked date", () => {
  const url = pathToFileURL(resolve(import.meta.dirname, "../components/linkedin-closure-badge.tsx")).href;
  for (const [zone, date] of [["America/Los_Angeles", "2026-10-10"], ["Asia/Jerusalem", "2026-10-11"]]) {
    const probe = spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "--eval", `
      import { renderToStaticMarkup } from "react-dom/server";
      import * as module from ${JSON.stringify(url)};
      const Badge = module.LinkedInClosureBadge ?? module.default?.LinkedInClosureBadge;
      const signal = { phrase: "no longer accepting applications", checked_at: "2026-10-11T00:30:00Z", url: "https://www.linkedin.com/jobs/view/123" };
      process.stdout.write(renderToStaticMarkup(Badge({ job: { linkedin_closed_signal: signal } })));
      if (Badge({ job: { linkedin_closed_signal: null } }) !== null) throw new Error("Missing signal must render nothing");
    `], { cwd: resolve(import.meta.dirname, ".."), encoding: "utf8", env: { ...process.env, TZ: zone } });
    assert.equal(probe.status, 0, probe.stderr);
    assert.match(probe.stdout, new RegExp(`title="LinkedIn: no longer accepting applications · checked ${date}"`));
    assert.match(probe.stdout, new RegExp(`>${date}</time>`));
    assert.match(probe.stdout, /dateTime="2026-10-11T00:30:00Z"/);
    assert.match(probe.stdout, /href="https:\/\/www.linkedin.com\/jobs\/view\/123"/);
  }
});
