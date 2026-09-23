import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";

const now = Date.parse("2026-09-08T12:00:00Z");
const found = "2026-09-08T10:00:00Z";
const posted = "2026-09-07T12:00:00Z";

function markup(postedAt: string | null, firstSeenAt: string | null): string {
  const componentUrl = pathToFileURL(resolve(import.meta.dirname, "../components/posting-dates.tsx")).href;
  const probe = spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "--eval", `
    import { renderToStaticMarkup } from "react-dom/server";
    import * as module from ${JSON.stringify(componentUrl)};
    const PostingDates = module.PostingDates ?? module.default?.PostingDates;
    process.stdout.write(renderToStaticMarkup(PostingDates(${JSON.stringify({ postedAt, firstSeenAt, now })})));
  `], { cwd: resolve(import.meta.dirname, ".."), encoding: "utf8" });
  assert.equal(probe.status, 0, probe.stderr);
  return probe.stdout;
}

test("posting and discovery ages are shown together with separate timestamps", () => {
  const rendered = markup(posted, found);
  assert.match(rendered, /Posted 1d ago.* · .*Found 2h ago/);
  assert.match(rendered, /dateTime="2026-09-07T12:00:00Z"/);
  assert.match(rendered, /dateTime="2026-09-08T10:00:00Z"/);
});

test("missing publish date shows only discovery age", () => {
  const rendered = markup(null, found);
  assert.match(rendered, /Found 2h ago/);
  assert.doesNotMatch(rendered, /Posted/);
});
