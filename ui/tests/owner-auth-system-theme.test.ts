import assert from "node:assert/strict";
import { test } from "node:test";

import { followSystemTheme } from "../lib/auth/system-theme";

test("signed-out auth follows the system theme and overrides any existing dashboard class", () => {
  let dark = true;
  let subscribed: ((event: { matches: boolean }) => void) | undefined;
  let removed: ((event: { matches: boolean }) => void) | undefined;
  const stop = followSystemTheme(
    {
      classList: {
        toggle(name, force) {
          assert.equal(name, "dark");
          dark = force;
        },
      },
    },
    {
      matches: false,
      addEventListener(type, listener) {
        assert.equal(type, "change");
        subscribed = listener;
      },
      removeEventListener(type, listener) {
        assert.equal(type, "change");
        removed = listener;
      },
    },
  );

  assert.equal(dark, false);
  subscribed?.({ matches: true });
  assert.equal(dark, true);
  stop();
  assert.equal(removed, subscribed);
});
