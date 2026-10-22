/** Replay a frozen JSONL snapshot, never a DB, model, or running service. */
import { createHash } from "node:crypto";
import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";
import { z } from "zod";
import { experiencePhrase } from "../lib/job-metadata";

async function main() {
  const [snapshot, baseline, output] = process.argv.slice(2);
  if (!snapshot || !baseline || !output) throw new Error("Usage: years-dryrun.ts SNAPSHOT BASELINE_TS OUTPUT");
  const previous: { experiencePhrase: typeof experiencePhrase } = await import(pathToFileURL(baseline).href);
  const rowSchema = z.object({
    id: z.string(), company: z.string(), raw_jd: z.string().nullable(),
    list_metadata: z.object({ experience: z.string().nullable() }).nullable(),
  });
  const bytes = readFileSync(snapshot);
  const rows = bytes.toString().split("\n").filter(line => line.trim()).map(line => rowSchema.parse(JSON.parse(line)));
  const changed = [];
  let stored = 0, before = 0, after = 0, gained = 0, dropped = 0;
  for (const row of rows) {
    const cached = row.list_metadata?.experience ?? null;
    const old = previous.experiencePhrase(row.raw_jd);
    const current = experiencePhrase(row.raw_jd);
    if (current && !row.raw_jd?.includes(current)) throw new Error(`Non-contiguous evidence: ${row.id}`);
    stored += Number(cached !== null); before += Number(old !== null); after += Number(current !== null);
    gained += Number(old === null && current !== null); dropped += Number(old !== null && current === null);
    if (cached !== current || old !== current) changed.push({ id: row.id, company: row.company, stored: cached, before: old, after: current,
      remark: current === null ? "No unambiguous required experience quote admitted by the grammar." : null });
  }
  const counts = { rows: rows.length, stored, before, after, gained, dropped, changed: changed.length };
  writeFileSync(output, ["# YEARS offline replay", "", "STATUS: frozen snapshot projection; no writes to services or databases.",
    `Snapshot SHA-256: ${createHash("sha256").update(bytes).digest("hex")}`, "",
    "Stored is the snapshot cache; before is the parent parser; after is the revised parser.",
    "Existing stored rows are unchanged until an operator applies the migration and explicitly refreshes cached metadata.",
    "", JSON.stringify(counts), "", "Every changed row (exact source quotes; null means unknown):", "", "```jsonl",
    ...changed.map(row => JSON.stringify(row)), "```", ""].join("\n"));
  console.log(JSON.stringify(counts));
}

void main();
