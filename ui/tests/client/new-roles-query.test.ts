import assert from "node:assert/strict";
import { test } from "node:test";
import { QueryClient } from "@tanstack/react-query";
import { newRolesQueryOptions } from "../../components/use-new-roles";

test("new-role queries poll every 90s, pause while hidden and focus only after a 15s quiet gap", t => {
  const options = newRolesQueryOptions("/api/jobs?since=fixture");
  assert.equal(options.refetchInterval, 90_000);
  assert.equal(options.refetchIntervalInBackground, false);
  assert.equal(options.staleTime, 15_000);
  const client = new QueryClient();
  t.after(() => client.clear());
  const query = client.getQueryCache().build(client, { ...options, queryKey: [...options.queryKey] });
  assert.equal(typeof options.refetchOnWindowFocus, "function");
  if (typeof options.refetchOnWindowFocus !== "function") throw new Error("Focus must respect the quiet gap");
  query.setState({ dataUpdatedAt: 1_000, errorUpdatedAt: 0 });
  const clock = t.mock.method(Date, "now", () => 15_999);
  assert.equal(options.refetchOnWindowFocus(query), false);
  clock.mock.mockImplementation(() => 16_000);
  assert.equal(options.refetchOnWindowFocus(query), true);
  query.setState({ errorUpdatedAt: 10_000 });
  clock.mock.mockImplementation(() => 24_999);
  assert.equal(options.refetchOnWindowFocus(query), false);
  clock.mock.mockImplementation(() => 25_000);
  assert.equal(options.refetchOnWindowFocus(query), true);
});
