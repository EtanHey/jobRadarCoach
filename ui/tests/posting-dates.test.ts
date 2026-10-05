import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";

const now = Date.parse("2026-09-08T12:00:00Z");
const found = "2026-09-08T10:00:00Z";
const posted = "2026-09-07T12:00:00Z";

function markup(postedAt: string | null, firstSeenAt: string | null, lastPublishedAt: string | null = null, extra: Record<string, unknown> = {}): string {
  const componentUrl = pathToFileURL(resolve(import.meta.dirname, "../components/posting-dates.tsx")).href;
  const probe = spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "--eval", `
    import { renderToStaticMarkup } from "react-dom/server";
    import * as module from ${JSON.stringify(componentUrl)};
    const PostingDates = module.PostingDates ?? module.default?.PostingDates;
    process.stdout.write(renderToStaticMarkup(PostingDates(${JSON.stringify({ postedAt, firstSeenAt, lastPublishedAt, now, timeZone: "UTC", ...extra })})));
  `], { cwd: resolve(import.meta.dirname, ".."), encoding: "utf8" });
  assert.equal(probe.status, 0, probe.stderr);
  return probe.stdout;
}

test("posted and found render as plus and search icons with compact ages and full labels", () => {
  const rendered = markup(posted, found);
  assert.match(rendered, /data-date-kind="posted"[^>]*aria-label="Posted 2026-09-07, 1 day ago"|aria-label="Posted 2026-09-07, 1 day ago"[^>]*data-date-kind="posted"/);
  assert.match(rendered, /aria-label="Found by JRC 2026-09-08 10:00, 2 hours ago"/);
  assert.match(rendered, /lucide-plus/);
  assert.match(rendered, /lucide-search/);
  assert.doesNotMatch(rendered, /lucide-recycle/);
  assert.match(rendered, />1d</);
  assert.match(rendered, />2h</);
  assert.doesNotMatch(rendered, /ago</);
  assert.match(rendered, /dateTime="2026-09-07T12:00:00Z"/);
  assert.match(rendered, /dateTime="2026-09-08T10:00:00Z"/);
});

test("missing publish date shows only discovery", () => {
  const rendered = markup(null, found);
  assert.match(rendered, /lucide-search/);
  assert.doesNotMatch(rendered, /lucide-plus|Posted/);
});

test("republication renders a recycle icon with its own timestamp", () => {
  const rendered = markup("2026-09-01T12:00:00Z", found, posted);
  assert.match(rendered, /aria-label="Posted 2026-09-01, 7 days ago".*aria-label="Republished 2026-09-07, 1 day ago".*aria-label="Found by JRC/);
  assert.match(rendered, /lucide-recycle/);
  assert.match(rendered, /dateTime="2026-09-01T12:00:00Z"/);
  assert.match(rendered, /dateTime="2026-09-07T12:00:00Z"/);
});

test("no recycle icon when the latest publication is the original one", () => {
  assert.doesNotMatch(markup(posted, found, posted), /lucide-recycle|Republished/);
});

test("the calendar-plus alternative swaps only the posted glyph", () => {
  const rendered = markup(posted, found, null, { postedIcon: "calendar-plus" });
  assert.match(rendered, /lucide-calendar-plus/);
  assert.match(rendered, /aria-label="Posted 2026-09-07, 1 day ago"/);
});

test("static mode renders no buttons so it can sit inside another button", () => {
  const rendered = markup(posted, found, null, { interactive: false });
  assert.doesNotMatch(rendered, /<button/);
  assert.match(rendered, /Posted 2026-09-07, 1 day ago/);
  assert.match(rendered, /lucide-plus/);
});

test("no dates renders an explicit unavailable label", () => {
  assert.match(markup(null, null), /Date unavailable/);
});
