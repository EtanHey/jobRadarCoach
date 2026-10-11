import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { NewRolesPill } from "../components/new-roles-pill";

test("new-role refresh action explains Show to screen readers", () => {
  for (const [count, label] of [[1, "Show 1 new role (refreshes the list)"], [3, "Show 3 new roles (refreshes the list)"]] as const) {
    const html = renderToStaticMarkup(React.createElement(NewRolesPill, { count, truncated: false, onShow() {} }));
    assert.ok(html.includes(`aria-label="${label}"`), `Expected accessible label: ${label}`);
  }
});
