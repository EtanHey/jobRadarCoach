import { createHash } from "node:crypto";

export function descriptionFingerprint(text: string | null): string | null {
  const normalized = text?.normalize("NFKC").trim().replace(/\s+/gu, " ").toLowerCase();
  // Short snippets are often reusable boilerplate, not role descriptions.
  return normalized && normalized.length >= 200 && normalized.split(" ").length >= 40
    ? createHash("sha256").update(normalized).digest("hex") : null;
}
