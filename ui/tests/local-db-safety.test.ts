import assert from "node:assert/strict";
import { test } from "node:test";
import { localStatus } from "../e2e/db/local.mjs";

const status = { API_URL: "https://127.0.0.1:55431", DB_URL: "postgresql://postgres:postgres@127.0.0.1:55432/postgres", MAILPIT_URL: "http://127.0.0.1:55434", ANON_KEY: "local-anon", SERVICE_ROLE_KEY: "local-service" };
test("test database refuses hosted, alternate-port and missing configuration", () => {
  assert.deepEqual(localStatus(status), status);
  for (const field of ["API_URL", "DB_URL", "MAILPIT_URL"] as const) {
    for (const value of ["https://prod.supabase.co", status[field].replace("127.0.0.1", "localhost"), status[field].replace(/5543\d/, "54321"), ""]) {
      assert.throws(() => localStatus({ ...status, [field]: value }));
    }
  }
  for (const field of ["ANON_KEY", "SERVICE_ROLE_KEY"]) assert.throws(() => localStatus({ ...status, [field]: "" }));
});
