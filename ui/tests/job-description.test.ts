import assert from "node:assert/strict";
import { test } from "node:test";

import {
  isSafeDescriptionUrl,
  parseDescriptionBlocks,
  parseDescriptionInline,
} from "../components/job-description";

test("description parser separates headings, paragraphs, and unordered lists", () => {
  assert.deepEqual(parseDescriptionBlocks("# Role\n\nFirst line\nsecond line\n\n- One\n* Two"), [
    { kind: "heading", level: 1, text: "Role" },
    { kind: "paragraph", text: "First line\nsecond line" },
    { kind: "list", items: ["One", "Two"] },
  ]);
});

test("inline parser supports bold and safe Markdown links while leaving unsafe syntax literal", () => {
  assert.deepEqual(
    parseDescriptionInline("Use **TypeScript**. [Apply](https://jobs.example/apply) [bad](javascript:alert(1))"),
    [
      { kind: "text", text: "Use " },
      { kind: "bold", text: "TypeScript" },
      { kind: "text", text: ". " },
      { kind: "link", label: "Apply", href: "https://jobs.example/apply" },
      { kind: "text", text: " [bad](javascript:alert(1))" },
    ],
  );
});

test("only absolute HTTP and HTTPS destinations are linkable", () => {
  assert.equal(isSafeDescriptionUrl("http://example.com/job"), true);
  assert.equal(isSafeDescriptionUrl("https://example.com/job?q=a"), true);
  assert.equal(isSafeDescriptionUrl("javascript:alert(1)"), false);
  assert.equal(isSafeDescriptionUrl("data:text/html,hello"), false);
  assert.equal(isSafeDescriptionUrl("/relative"), false);
});

test("raw HTML and unmatched Markdown remain text", () => {
  assert.deepEqual(parseDescriptionInline("<script>alert(1)</script> **open"), [
    { kind: "text", text: "<script>alert(1)</script> **open" },
  ]);
});


test("plain-text bullet glyphs keep list structure without blank separator lines", () => {
  assert.deepEqual(parseDescriptionBlocks("Responsibilities\n• Build accessible UI\n• Test keyboard paths\nRequirements\n‣ Know TypeScript"), [
    { kind: "paragraph", text: "Responsibilities" },
    { kind: "list", items: ["Build accessible UI", "Test keyboard paths"] },
    { kind: "paragraph", text: "Requirements" },
    { kind: "list", items: ["Know TypeScript"] },
  ]);
  assert.deepEqual(parseDescriptionBlocks("Use foo•bar and C++ safely."), [
    { kind: "paragraph", text: "Use foo•bar and C++ safely." },
  ]);
});
