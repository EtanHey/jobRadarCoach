import assert from "node:assert/strict";
import { createClient } from "@supabase/supabase-js";
import { selectSummaries } from "../../lib/server";
async function main() {
  const db = createClient("http://fixture.invalid", "synthetic-key", { auth: { persistSession: false }, global: {
    fetch: async (input, init) => {
      const url = new URL(String(input)), headers = new Headers(init?.headers);
      // Disposable standalone PostgREST has no Supabase gateway or JWT secret.
      headers.delete("authorization");
      const response = await fetch(`${process.env.JOBRADAR_TEST_REST_URL}${url.pathname.replace(/^\/rest\/v1/, "")}${url.search}`, { ...init, headers });
      if (!response.ok) console.error(response.status, await response.clone().text());
      return response;
    },
  } });
  const rows = await selectSummaries(db, { filter: "all", availability: "all", fit: "", statuses: [], sort: "fit", limit: 1000 });
  const pipeline = await selectSummaries(db, { filter: "all", availability: "all", fit: "recommended", statuses: ["applied", "worth_checking"], sort: "fit", limit: 1000 });
  assert.ok(pipeline.length > 0);
  assert.ok(pipeline.every(row => ["applied", "worth_checking"].includes(row.status) && ["apply", "review", "referral"].includes(row.recommendation ?? "")));
  const window = await selectSummaries(db, { filter: "all", availability: "all", sort: "fit", limit: 1000, found_within: "30d" });
  assert.ok(window.every(row => Date.parse(row.first_seen_at) >= Date.now() - 30 * 86400000 - 1000));
  assert.ok(!window.some(row => row.id === rows[0].id), "old highest-fit row is excluded before cap");
  const poll = await selectSummaries(db, { filter: "all", availability: "all", limit: 101, since: "1970-01-01T00:00:00Z", found_within: "24h" });
  assert.ok(poll.every(row => Date.parse(row.first_seen_at) >= Date.now() - 86400000 - 1000));
  process.stdout.write(JSON.stringify({ first: rows[0].id, count: rows.length, pipeline: true, window: true, poll: true }));
}
void main();
