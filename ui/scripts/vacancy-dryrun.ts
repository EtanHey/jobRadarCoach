import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import assert from "node:assert/strict";
import { createClient } from "@supabase/supabase-js";
import { z } from "zod";
import { GlobeJobSchema } from "../lib/globe-contract";
import { groupDuplicateJobs } from "../lib/job-dedup";
import { vacancyBodyCandidates, withVacancyIdentity } from "../lib/vacancy-server";

async function main() {
  const [snapshotPath, summaryPath, reportPath, baselineRef = "master"] = process.argv.slice(2);
  const snapshot = readFileSync(snapshotPath, "utf8");
  const bodies = new Map<string,string|null>();
  const jobs = snapshot.trim().split("\n").map(line => z.object({
    raw_jd: z.string().nullable(), posting_status: z.object({status: z.string(), reason: z.string().nullable()}).nullable(),
    posting_scores: z.object({score: z.number().nullable()}).nullable(),
    liveness: z.object({alive: z.boolean().optional()}).passthrough().nullable(),
  }).passthrough().parse(JSON.parse(line))).map(row => {
    const job = GlobeJobSchema.parse({...row, status: row.posting_status?.status ?? "new", status_reason: row.posting_status?.reason ?? null,
      score: row.posting_scores?.score ?? null, recommendation: null, alive: row.liveness?.alive ?? null});
    bodies.set(job.id,row.raw_jd);
    return job;
  });
  const batches: number[] = [];
  const db = createClient("https://offline.example.test","synthetic",{global:{fetch:async input=>{
    const url = new URL(String(input));
    assert.equal(url.searchParams.get("select"),"id,identity_evidence:raw_jd");
    const ids = (url.searchParams.get("id") ?? "").slice(4,-1).split(",");
    assert.ok(ids.length > 0 && ids.length <= 100);
    batches.push(ids.length);
    return Response.json(ids.map(id=>({id,identity_evidence:bodies.get(id)})));
  }}});
  const rows = await withVacancyIdentity(db,jobs);
  const candidateCount = vacancyBodyCandidates(jobs).length;
  const fetchedCount = batches.reduce((sum,size)=>sum+size,0);
  assert.ok(fetchedCount <= 300);
  assert.ok(rows.every(row=>!("raw_jd" in row) && !("identity_evidence" in row)));
  const baselinePath = new URL(`../lib/job-dedup-baseline-${randomUUID()}.local.ts`, import.meta.url);
  writeFileSync(baselinePath, execFileSync("git", ["show", `${baselineRef}:ui/lib/job-dedup.ts`]));
  try {
    const baseline: typeof import("../lib/job-dedup") = await import(baselinePath.href);
    const before = baseline.groupDuplicateJobs(rows), after = groupDuplicateJobs(rows);
    const members = (group: typeof after[number]) => [group.job, ...group.alternates];
    const covered = after.flatMap(members).map(job => job.id);
    if (covered.length !== rows.length || new Set(covered).size !== rows.length) throw new Error("Coverage failure");
    const originalById = new Map(rows.map(row => [row.id, row]));
    for (const member of after.flatMap(members)) {
      const original = originalById.get(member.id);
      assert.ok(original);
      for (const field of ["company", "source", "location", "alive", "score", "url", "apply_url"] as const) {
        assert.deepEqual(member[field], original[field], `${member.id}: preserved ${field}`);
      }
    }
    for (const [name, ids] of [
      ["Unframe", ["7c3ef744-26a4-4a05-8485-febbe4130ee2", "97994440-a6f6-4f8b-80a4-66cb6b13b57d"]],
      ["Office Hours", ["6270b19b-5d99-4d5b-a905-6e0968fac867", "7cf0dfb5-252b-4178-b151-55a8358f16ee"]],
    ] as const) {
      const pair = rows.filter(row => ids.some(id => id === row.id));
      assert.equal(pair.length, 2, `${name}: frozen pair present`);
      for (const input of [pair, pair.toReversed()]) {
        assert.equal(baseline.groupDuplicateJobs(input).length, 1, `${name}: master control`);
        assert.equal(groupDuplicateJobs(input).length, 1, `${name}: frozen snapshot regression`);
      }
    }
    const conflicts = after.filter(group => new Set(members(group).flatMap(job => job.vacancy_identity?.requisitions ?? [])).size > 1 && members(group).length > 1);
    const afterById = new Map(after.flatMap((group, index) => members(group).map(job => [job.id, index] as const)));
    const splits = before.flatMap(group => {
      const partitions = new Map<number, typeof rows>();
      for (const row of members(group)) {
        const index = afterById.get(row.id);
        assert.ok(index !== undefined);
        const partition = partitions.get(index);
        if (partition) partition.push(row); else partitions.set(index, [row]);
      }
      if (partitions.size < 2) return [];
      const parts = [...partitions.values()].map(rows => ({rows,
        requisitions: [...new Set(rows.flatMap(row => row.vacancy_identity?.requisitions ?? []))],
      }));
      const distinct = parts.every(part => part.requisitions.length === 1)
        && new Set(parts.flatMap(part => part.requisitions)).size === parts.length;
      return [{company: group.job.company, title: group.job.title, parts, distinct}];
    });
    const beforeById = new Map(before.flatMap((group, index) => members(group).map(job => [job.id, index] as const)));
    const masterSeparatePairs = after.flatMap(group => {
      const jobs = members(group);
      return jobs.flatMap((left, index) => jobs.slice(index + 1)
        .filter(right => beforeById.get(left.id) !== beforeById.get(right.id))
        .map(right => ({left, right})));
    });
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
      ...subgroups.map(group => `| ${group.name} | ${group.ids.length} | ${count(before,group.ids)} | ${count(after,group.ids)} | ${[...new Set(rows.filter(row => group.ids.includes(row.id)).flatMap(row => row.vacancy_identity?.requisitions ?? []))].join(", ") || "none"} |`), "",
      `Candidate bodies: ${candidateCount}; fetched: ${fetchedCount}; batches: ${batches.join(", ")}; maximum batch: ${Math.max(0,...batches)}; request cap: 300.`, "",
      "Counts intersect each subgroup with the full snapshot grouping, not a separate isolated run. No row is deleted or written to a database. Source IDs, sources, URLs, locations, per-source liveness and scores are checked against the original rows. Both frozen Unframe and Office Hours pairs group to one in either input order.", "",
      "## Every baseline group that split", "",
      `${splits.length} baseline groups split, adding ${splits.reduce((sum, split) => sum + split.parts.length - 1, 0)} groups before merges elsewhere. Splits without distinct known requisition evidence: ${splits.filter(split => !split.distinct).length}.`, "",
      ...splits.flatMap((split, index) => [
        `${index + 1}. **${split.company} — ${split.title}: 1 → ${split.parts.length}.** ${split.distinct ? "Genuine distinct employer requisitions." : "UNPROVEN split: no distinct requisition evidence."}`,
        ...split.parts.map(part => `   - ${part.requisitions.join(", ") || "unknown requisition"}: ${part.rows.map(row => `\`${row.id}\``).join(", ")}`), "",
      ]),
      "## Master-separate → branch-merged snapshot pairs", "",
      `${masterSeparatePairs.length} pairs. This is the exhaustive literal group-membership comparison, including intended same-vacancy merges. The NVIDIA target itself requires merging some master-separated groups (33 → 21), so an empty full-snapshot list is incompatible with that target.`, "",
      "| Company | Left posting | Right posting | Requisitions |",
      "|---|---|---|---|",
      ...masterSeparatePairs.map(({left, right}) => `| ${left.company} | ${left.id} | ${right.id} | ${[...new Set([...(left.vacancy_identity?.requisitions ?? []), ...(right.vacancy_identity?.requisitions ?? [])])].join(", ") || "none"} |`), "",
      "The three reviewer technology-collision pairs remain separate in raw and compact form in both input orders (focused tests); their master-separate → branch-merged list is EMPTY.", "",
      "## Identity and fallback rule", "",
      "Strong identity uses employer requisitions from labelled JD fields (including Job Req), unlabelled JR IDs with at least five digits in the JD, or Workday URL path segments _JR<digits> / _R<at least five digits>. Bare R IDs are never extracted from JD text. Greenhouse posting IDs (jobs path, gh_jid, embed token), Lever UUIDs, Comeet position UIDs and Workable shortcodes remain posting/link evidence. They cannot veto a JD match.", "",
      "Without conflicting known requisitions, identical normalized JDs merge even with title/location drift. Different JD fingerprints fall through to the existing title/role-URL and compatible-location heuristic. A changed hash cannot prove distinct headcount: this conservative fallback restores the nine unknown-requisition baseline groups split in R1, including Office Hours. Different titles and posting URLs with substantively different JDs stay separate; known distinct requisitions always stay separate even with matching titles, locations and JDs. This intentionally does not infer distinct headcount from substantive wording changes alone.", "",
      "Board, globe and new-role membership projections omit raw_jd. Identity uses URLs first; only unique rows of repeated normalized employers without URL requisitions fetch bodies, in batches of at most 100 with a 300-row cap per request and a warning on overflow. This offline run exercises the shared server helper with snapshot-backed evidence responses. Bodies do not cross the browser wire. Identity can reflect a later JD edit; membership/geo/cutoff remain from the original snapshot.", "",
      "Offline function evidence only. No hosted dashboard, production DB, browser visual QA, or ingest change is claimed.", ""];
    writeFileSync(reportPath, lines.join("\n"));
    process.stdout.write(lines.slice(0,8).join("\n") + "\n");
    process.stdout.write(`Candidate bodies: ${candidateCount}; fetched: ${fetchedCount}; max batch: ${Math.max(0,...batches)}; request cap: 300.\n`);
    assert.equal(before.length,582);
    assert.equal(after.length,574);
    if (conflicts.length || count(after,nvidiaIds) !== 21 || splits.some(split => !split.distinct)) process.exitCode = 1;
  } finally { unlinkSync(baselinePath); }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
