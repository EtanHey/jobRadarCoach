import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { test } from "node:test";
import { pathToFileURL } from "node:url";
import { JobStatusSchema } from "../lib/contracts";
import { statusDimsCard } from "../lib/job-status";

const uiRoot = resolve(import.meta.dirname, "..");
const id = "00000000-0000-4000-8000-000000000001";

test("only terminal statuses dim a card in every view; Seen and the live pipeline stay at full strength", () => {
  const dimmed = JobStatusSchema.options.filter(statusDimsCard);
  assert.deepEqual(dimmed, ["skipped", "applied", "contract", "rejected", "archived", "not_relevant"]);
});

function renderCard(overrides: Record<string, unknown>, keptStatus: string | null = null): string {
  const cardUrl = pathToFileURL(resolve(uiRoot, "components/job-card.tsx")).href;
  const job = { id, title: "Fixture engineer", company: "Fixture", source: "fixture",
    last_seen_at: "2026-10-04T00:00:00Z", experience: null, description_available: false, seniority_origin: "unknown", extraction_state: "not-extracted",
    location: "Tel Aviv-Yafo, Israel (Hybrid)", remote: null, seniority: null, stack: [], salary: null, url: "https://example.test", apply_url: null,
    posted_at: null, first_seen_at: "2026-10-04T00:00:00Z", status: "seen", status_reason: null, score: 80, fit_line: null, recommendation: null, alive: true, ...overrides };
  const probe = spawnSync(process.execPath, ["--import", "tsx", "--input-type=module", "--eval", `
    import React from "react";
    import { renderToStaticMarkup } from "react-dom/server";
    const module = await import(${JSON.stringify(cardUrl)});
    const JobCard = module.JobCard ?? module.default?.JobCard;
    process.stdout.write(renderToStaticMarkup(React.createElement(JobCard, { job: ${JSON.stringify(job)}, keptStatus: ${JSON.stringify(keptStatus)}, openerRef: { current: null }, selectJob() {} })));
  `], { cwd: uiRoot, encoding: "utf8" });
  assert.equal(probe.status, 0, probe.stderr);
  return probe.stdout;
}

test("every view shows a status chip under the score box, never on the location row", () => {
  const html = renderCard({ status: "seen" });
  const score = html.indexOf('aria-label="Fit score 80 out of 100"');
  const chip = html.indexOf('data-card-status="seen"');
  const location = html.indexOf("Tel Aviv-Yafo");
  assert.ok(score > -1 && chip > score, "the chip follows the score box");
  assert.ok(chip < location, "the chip sits in the header, above the location row");
  assert.match(html, /data-card-status="seen" title="Seen"[^>]*>Seen<\/span>/);
  assert.match(html, new RegExp(`<button[^>]+aria-describedby="card-status-${id}"`), "the status is announced with the card's button");
});

test("a new card has no chip and no dim", () => {
  const html = renderCard({ status: "new" });
  assert.doesNotMatch(html, /data-card-status|opacity-60|aria-describedby/);
});

test("outside New for me Seen gets a quiet chip without dimming; terminal statuses dim the content, never the frame", () => {
  assert.doesNotMatch(renderCard({ status: "seen" }), /opacity-60/);
  assert.doesNotMatch(renderCard({ status: "interview_technical" }), /opacity-60/);
  for (const status of ["applied", "rejected", "not_relevant"]) {
    const html = renderCard({ status });
    assert.match(html, /opacity-60/, status);
    assert.doesNotMatch(html, /<article[^>]+class="[^"]*opacity-/, `${status}: the frame keeps full-strength hover and focus rings`);
    assert.match(html, /data-card-status="[a-z_]+" title="[^"]+" class="[^"]*opacity-60/, `${status}: the chip itself is dimmed with the content`);
  }
});

test("worth checking is a text chip, not a bare bookmark", () => {
  const html = renderCard({ status: "worth_checking" });
  assert.match(html, /data-card-status="worth_checking"[^>]*>Worth checking</);
  assert.doesNotMatch(html, /lucide-bookmark/);
});

test("New for me keeps its settled marker on kept cards and dims a kept Seen card like a terminal one", () => {
  const seen = renderCard({ status: "seen" }, "seen");
  assert.match(seen, /<article[^>]+data-settled=""/);
  assert.doesNotMatch(seen, /<article[^>]+class="[^"]*opacity-/, "the frame keeps full-strength hover and focus rings");
  assert.match(seen, /<div class="[^"]*opacity-60[^"]*"><div[^>]*><p class="truncate">Fixture<\/p>/, "the title block is dimmed");
  assert.match(seen, /data-card-status="seen" title="Seen" class="[^"]*opacity-60/, "the Seen chip is dimmed with the content");
  assert.match(seen, new RegExp(`<button[^>]+aria-describedby="card-status-${id}"`), "the status is still announced with the card's button");
  assert.match(renderCard({ status: "applied" }, "applied"), /opacity-60/);
  // Only Seen joins the terminal statuses in New for me; the live pipeline stays at full strength there too.
  assert.doesNotMatch(renderCard({ status: "worth_checking" }, "worth_checking"), /opacity-60/);
  assert.doesNotMatch(renderCard({ status: "interview_technical" }, "interview_technical"), /opacity-60/);
  // All roles and the Seen view pass no kept status: Seen stays undimmed there.
  assert.doesNotMatch(renderCard({ status: "seen" }), /data-settled|opacity-60/);
});

test("work mode renders as an icon with its text as the accessible name, not as location text", () => {
  const cases = [
    [{ remote: true }, "remote", "Remote", "lucide-monitor-cloud"],
    [{ remote: false }, "on-site", "On-site", "lucide-building-2"],
    [{ remote: null, work_mode: "hybrid" }, "hybrid", "Hybrid", "lucide-screen-share"],
    [{ remote: null }, "unknown", "Work mode unspecified", "lucide-file-question-mark"],
  ] as const;
  for (const [fields, kind, label, icon] of cases) {
    const html = renderCard(fields);
    assert.match(html, new RegExp(`<span[^>]+data-work-mode="${kind}"[^>]+role="img"[^>]+aria-label="${label}" title="${label}"[^>]*><svg[^>]+class="[^"]*${icon}`), kind);
    assert.doesNotMatch(html, new RegExp(`·\\s*${label}`), `${kind}: the mode is no longer appended to the location text`);
  }
});
