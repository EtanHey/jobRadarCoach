import assert from "node:assert/strict";
import { test } from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { NewRolesPill } from "../components/new-roles-pill";

test("new-role refresh action explains Show to screen readers", () => {
  const html = renderToStaticMarkup(React.createElement(NewRolesPill, { count: 1, truncated: false, onShow() {} }));
  assert.match(html, /aria-label="1 new role[^"]*Show refreshes the list"/);
});
