import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createHash } from "node:crypto";
import { z } from "zod";
import { GlobeJobSchema } from "../lib/globe-contract";
import { groupDuplicateJobs } from "../lib/job-dedup";
import { vacancyIdentity } from "../lib/vacancy-identity";

async function main() {
  const [snapshotPath, summaryPath, reportPath, baselineRef = "master"] = process.argv.slice(2);
  const snapshot = readFileSync(snapshotPath, "utf8");
  const rows = snapshot.trim().split("\n").map(line => z.object({
    raw_jd: z.string().nullable(), posting_status: z.object({status: z.string(), reason: z.string().nullable()}).nullable(),
    posting_scores: z.object({score: z.number().nullable()}).nullable(),
    liveness: z.object({alive: z.boolean().optional()}).passthrough().nullable(),
  }).passthrough().parse(JSON.parse(line))).map(row => {
    const job = GlobeJobSchema.parse({...row, status: row.posting_status?.status ?? "new", status_reason: row.posting_status?.reason ?? null,
      score: row.posting_scores?.score ?? null, recommendation: null, alive: row.liveness?.alive ?? null});
    return {...job, vacancy_identity: vacancyIdentity({...job, raw_jd: row.raw_jd})};
  });
  const baselinePath = new URL("../lib/job-dedup-baseline.local.ts", import.meta.url);
  writeFileSync(baselinePath, execFileSync("git", ["show", `${baselineRef}:ui/lib/job-dedup.ts`]));
  try {
    const baseline: typeof import("../lib/job-dedup") = await import(baselinePath.href);
    const before = baseline.groupDuplicateJobs(rows), after = groupDuplicateJobs(rows);
    const members = (group: typeof after[number]) => [group.job, ...group.alternates];
    const covered = after.flatMap(members).map(job => job.id);
    if (covered.length !== rows.length || new Set(covered).size !== rows.length) throw new Error("Coverage failure");
    const conflicts = after.filter(group => new Set(members(group).flatMap(job => job.vacancy_identity.requisitions)).size > 1 && members(group).length > 1);
    const family = readFileSync(summaryPath, "utf8").split("### 1. Repeated requisition/content identity")[1].split("### 2.")[0];
    const subgroups = family.split("\n").filter(line => /^- (?:JR\d+|`ISSUE-)/u.test(line)).map(line => ({
      name: line.match(/^- (JR\d+|`ISSUE-[^`]+`)/u)?.[1] ?? "unknown",
      ids: [...line.matchAll(/`([a-f\d-]{36})`/gu)].map(match => match[1]),
    }));
    const count = (groups: typeof after, ids: string[]) => groups.filter(group => members(group).some(job => ids.includes(job.id))).length;
    const nvidiaIds = subgroups.filter(group => group.name.startsWith("JR")).flatMap(group => group.ids);
    const lines = ["# P5 vacancy grouping offline dry-run", "", `Baseline: ${execFileSync("git", ["rev-parse", baselineRef], {encoding:"utf8"}).trim()}.`,
      `Snapshot SHA-256: ${createHash("sha256").update(snapshot).digest("hex")}.`,
      `Rows retained: ${covered.length}/${rows.length}. Visible groups: ${before.length} before → ${after.length} after.`,
      `NVIDIA cited subset: ${nvidiaIds.length} rows; ${count(before,nvidiaIds)} before → ${count(after,nvidiaIds)} after (target 21).`,
      `Groups merging different known requisitions: ${conflicts.length}.`, "", "| Triage subgroup | Rows | Before | After | Known requisitions |", "|---|---:|---:|---:|---|",
      ...subgroups.map(group => `| ${group.name} | ${group.ids.length} | ${count(before,group.ids)} | ${count(after,group.ids)} | ${[...new Set(rows.filter(row => group.ids.includes(row.id)).flatMap(row => row.vacancy_identity.requisitions))].join(", ") || "none"} |`), "",
      "Counts intersect each subgroup with the full snapshot grouping, not a separate isolated run. Different known requisitions stay separate even with identical JD text; differing employers and substantive JD variants remain candidates for manual review. No row is deleted or written to a database.", "",
      "UI transport derives compact identity from existing raw_jd server-side; bodies do not cross the board/globe wire. Globe evidence is read by captured IDs in batches of 100 after its membership snapshot. Identity can therefore reflect a later JD edit; membership/geo/cutoff remain from the original snapshot.", "",
      "Offline function evidence only. No hosted dashboard, production DB, browser visual QA, or ingest change is claimed.", ""];
    writeFileSync(reportPath, lines.join("\n"));
    process.stdout.write(lines.slice(0,8).join("\n") + "\n");
    if (conflicts.length || count(after,nvidiaIds) !== 21) process.exitCode = 1;
  } finally { unlinkSync(baselinePath); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
