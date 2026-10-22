import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { execFileSync } from "node:child_process";
import { createHash, randomUUID } from "node:crypto";
import assert from "node:assert/strict";
import { createClient } from "@supabase/supabase-js";
import { z } from "zod";
import { GlobeJobSchema } from "../lib/globe-contract";
import { groupDuplicateJobs } from "../lib/job-dedup";
import { vacancyIdentity } from "../lib/vacancy-identity";
import { withVacancyIdentity } from "../lib/vacancy-server";

async function main() {
  const [snapshotPath, reportPath, baselineRef = "17977d668149f437b31b866975688cdd56e719bd"] = process.argv.slice(2);
  const snapshot = readFileSync(snapshotPath, "utf8");
  const bodies = new Map<string, string | null>();
  const jobs = snapshot.trim().split("\n").map(line => z.object({
    raw_jd: z.string().nullable(), posting_status: z.object({status: z.string(), reason: z.string().nullable()}).nullable(),
    posting_scores: z.object({score: z.number().nullable()}).nullable(),
    liveness: z.object({alive: z.boolean().optional()}).passthrough().nullable(),
  }).passthrough().parse(JSON.parse(line))).map(row => {
    const job = GlobeJobSchema.parse({...row, status: row.posting_status?.status ?? "new", status_reason: row.posting_status?.reason ?? null,
      score: row.posting_scores?.score ?? null, recommendation: null, alive: row.liveness?.alive ?? null});
    bodies.set(job.id, row.raw_jd);
    return job;
  });
  const batches: number[] = [];
  const db = createClient("https://offline.example.test", "synthetic", {global:{fetch:async input => {
    const url = new URL(String(input));
    assert.equal(url.searchParams.get("select"), "id,identity_evidence:raw_jd");
    const ids = (url.searchParams.get("id") ?? "").slice(4,-1).split(",");
    assert.ok(ids.length > 0 && ids.length <= 100);
    batches.push(ids.length);
    return Response.json(ids.map(id => ({id,identity_evidence:bodies.get(id)})));
  }}});
  // Load the entire old identity/enrichment path, not old grouping over new identities.
  const suffix = `baseline-${randomUUID()}.local`;
  const modules = ["vacancy-identity", "job-dedup", "vacancy-server"];
  const paths = modules.map(name => new URL(`../lib/${name}-${suffix}.ts`, import.meta.url));
  try {
    for (const [index, name] of modules.entries()) {
      let source = execFileSync("git", ["show", `${baselineRef}:ui/lib/${name}.ts`], {encoding:"utf8"});
      for (const dependency of modules) source = source.replaceAll(`"./${dependency}"`, `"./${dependency}-${suffix}"`);
      writeFileSync(paths[index], source);
    }
    const baseline: typeof import("../lib/job-dedup") = await import(paths[1].href);
    const oldIdentity: typeof import("../lib/vacancy-identity") = await import(paths[0].href);
    const oldServer: typeof import("../lib/vacancy-server") = await import(paths[2].href);
    const beforeRows = await oldServer.withVacancyIdentity(db, jobs);
    const beforeBatches = batches.splice(0);
    const afterRows = await withVacancyIdentity(db, jobs);
    assert.ok(batches.reduce((sum,size) => sum+size,0) <= 300);
    assert.ok(afterRows.every(row => !("raw_jd" in row) && !("identity_evidence" in row)));
    const before = baseline.groupDuplicateJobs(beforeRows), after = groupDuplicateJobs(afterRows);
    const members = (group: typeof after[number]) => [group.job, ...group.alternates];
    const membership = (groups: typeof after) => new Map(groups.flatMap(group => {
      const ids = members(group).map(row => row.id).sort();
      return ids.map(id => [id, ids.join(",")] as const);
    }));
    const oldMembership = membership(before), newMembership = membership(after);
    const changed = jobs.filter(job => oldMembership.get(job.id) !== newMembership.get(job.id));
    const covered = after.flatMap(members).map(job => job.id);
    assert.equal(covered.length, jobs.length);
    assert.equal(new Set(covered).size, jobs.length);
    const originals = new Map(afterRows.map(row => [row.id,row]));
    for (const row of after.flatMap(members)) for (const field of ["company","source","location","alive","score","url","apply_url"] as const) {
      assert.deepEqual(row[field], originals.get(row.id)?.[field]);
    }
    const conflicts = after.filter(group => new Set(members(group).map(row => row.vacancy_identity?.requisitions)
      .filter(reqs => reqs?.length).map(reqs => [...new Set(reqs)].sort().join(","))).size > 1);
    const lengths = jobs.map(job => Number(oldIdentity.jdFingerprint(bodies.get(job.id))?.split(":")[1] ?? 0)).sort((a,b) => a-b);
    const changedIdentities = afterRows.flatMap((row,index) => JSON.stringify(row.vacancy_identity) === JSON.stringify(beforeRows[index].vacancy_identity) ? [] : [row.id]);
    const lines = ["# P5b frozen snapshot dry run", "", `Baseline: ${baselineRef}.`,
      `Snapshot SHA-256: ${createHash("sha256").update(snapshot).digest("hex")}.`,
      `Rows retained: ${covered.length}/${jobs.length}. Groups: ${before.length} → ${after.length}; delta ${after.length-before.length} versus 574.`,
      `Different known-requisition set merges: ${conflicts.length}. Changed group memberships: ${changed.length} rows.`,
      `Body batches before: ${beforeBatches.join(", ")}; after: ${batches.join(", ")}.`, "",
      `Normalized body distribution over all ${lengths.length} rows (using baseline normalization): empty ${lengths.filter(n=>n===0).length}; 1–399 ${lengths.filter(n=>n>0&&n<400).length}; 400–999 ${lengths.filter(n=>n>=400&&n<1000).length}; >=1000 ${lengths.filter(n=>n>=1000).length}.`,
      `Minimum nonempty length: ${lengths.find(n=>n>0)}. 400 characters rejects the two snippet bodies while retaining all ${lengths.filter(n=>n>=400).length} longer bodies.`, "",
      `Changed hydrated identities: ${changedIdentities.length}.`, ...changedIdentities.map(id => `- ${id}: ${JSON.stringify(beforeRows.find(row=>row.id===id)?.vacancy_identity)} → ${JSON.stringify(afterRows.find(row=>row.id===id)?.vacancy_identity)}`), "",
      "## Group changes", "", ...changed.map(row => `- ${row.id}: ${oldMembership.get(row.id)} → ${newMembership.get(row.id)}`),
      ...(changed.length ? [] : ["No membership changes: items 1/3/4 change no visible grouping in the capped snapshot. The shorter bodies and removed Job-number label do not supply a decisive cross-title match; no identical multi-requisition set changes a group."]), "",
      "Offline snapshot-backed Supabase enrichment only; no production writes, browser verification or hosted CI claim.", ""];
    writeFileSync(reportPath, lines.join("\n"));
    process.stdout.write(lines.slice(0,8).join("\n") + "\n");
    assert.equal(before.length,574);
    assert.equal(conflicts.length,0);
    // Any membership delta needs an explicit item 1/3/4 explanation before acceptance.
    assert.equal(changed.length,0);
    assert.deepEqual(vacancyIdentity({url:"https://example.test",apply_url:null,raw_jd:"Job number: 979"}).requisitions,[]);
  } finally { for (const path of paths) { try { unlinkSync(path); } catch { /* May fail before all modules are written. */ } } }
}
main().catch(error => { console.error(error); process.exitCode = 1; });
