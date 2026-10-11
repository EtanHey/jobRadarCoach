import assert from "node:assert/strict";
import { createClient } from "@supabase/supabase-js";
import { selectSummaries } from "../../lib/server";
import { parseSummaryRows } from "../../lib/server";
import { JobListResponseSchema } from "../../lib/contracts";
import { writeFile } from "node:fs/promises";
async function main() {
  let dbBytes = 0;
  const db = createClient("http://fixture.invalid", "synthetic-key", { auth: { persistSession: false }, global: {
    fetch: async (input, init) => {
      const url = new URL(String(input)), headers = new Headers(init?.headers);
      // Disposable standalone PostgREST has no Supabase gateway or JWT secret.
      headers.delete("authorization");
      const response = await fetch(`${process.env.JOBRADAR_TEST_REST_URL}${url.pathname.replace(/^\/rest\/v1/, "")}${url.search}`, { ...init, headers });
      if (!response.ok) console.error(response.status, await response.clone().text());
      dbBytes = Buffer.byteLength(await response.clone().text());
      return response;
    },
  } });
  const rows = await selectSummaries(db, { filter: "all", availability: "all", fit: "", statuses: [], sort: "fit", limit: 1000 });
  const afterDb = dbBytes;
  // Freeze the old projection here so the reduction is measured over the same
  // actual PostgREST rows/order, rather than estimated from a hand-built object.
  const beforeSelect = "relevance_filtered,relevance_gate,source,last_seen_at,list_metadata,liveness,posting_extractions(posting_id),id,title,company,location,remote,work_mode,seniority,stack,salary,url,apply_url,posted_at,last_published_at,first_seen_at,posting_status(status,reason),posting_scores(score,score_payload)";
  const before = await db.rpc("board_postings", { filter: "all", availability: "all", fit: "", statuses: [], sort: "fit", max: 1000 }).select(beforeSelect);
  assert.equal(before.error, null);
  const beforeRows = before.data;
  assert.ok(Array.isArray(beforeRows));
  const beforeDb = dbBytes;
  const legacy = parseSummaryRows(beforeRows).jobs;
  assert.deepEqual(JobListResponseSchema.parse({ jobs: rows }), JobListResponseSchema.parse({ jobs: legacy }));
  const oldWire = legacy.map((row, i) => ({ ...row, salary: beforeRows[i].salary,
    description_available: beforeRows[i].list_metadata.description_available,
    seniority_origin: beforeRows[i].seniority ? "extracted" : row.seniority ? "title" : "unknown",
    extraction_state: beforeRows[i].posting_extractions ? "extracted" : "not-extracted" }));
  const beforeBrowser = Buffer.byteLength(JSON.stringify({ jobs: oldWire }));
  const afterBrowser = Buffer.byteLength(JSON.stringify(JobListResponseSchema.parse({ jobs: rows })));
  assert.ok(afterDb < beforeDb);
  assert.ok(afterBrowser < beforeBrowser);
  if (process.env.JOBRADAR_PAYLOAD_RECEIPT) await writeFile(process.env.JOBRADAR_PAYLOAD_RECEIPT,
    JSON.stringify({ rows: rows.length, db: { before: beforeDb, after: afterDb }, browser: { before: beforeBrowser, after: afterBrowser } }, null, 2));
  const pipeline = await selectSummaries(db, { filter: "all", availability: "all", fit: "recommended", statuses: ["applied", "worth_checking"], sort: "fit", limit: 1000 });
  assert.ok(pipeline.length > 0);
  assert.ok(pipeline.every(row => ["applied", "worth_checking"].includes(row.status) && ["apply", "review", "referral"].includes(row.recommendation ?? "")));
  const window = await selectSummaries(db, { filter: "all", availability: "all", sort: "fit", limit: 1000, found_within: "30d" });
  assert.ok(window.every(row => Date.parse(row.first_seen_at) >= Date.now() - 30 * 86400000 - 1000));
  assert.ok(!window.some(row => row.id === rows[0].id), "old highest-fit row is excluded before cap");
  const poll = await selectSummaries(db, { filter: "all", availability: "all", limit: 101, since: "1970-01-01T00:00:00Z", found_within: "24h" });
  assert.ok(poll.every(row => Date.parse(row.first_seen_at) >= Date.now() - 86400000 - 1000));
  const facets = await selectSummaries(db, { filter: "all", availability: "all", limit: 1000, source: "synthetic", work_mode: "hybrid", location: "israel", seniority: "Junior" });
  assert.deepEqual(facets.map(row => row.id), [rows[0].id]);
  process.stdout.write(JSON.stringify({ first: rows[0].id, count: rows.length, pipeline: true, window: true, poll: true, facets: true }));
}
void main();
