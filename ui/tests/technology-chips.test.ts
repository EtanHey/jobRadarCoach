import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  technologyChipWindow,
  technologyIconFor,
  technologyKind,
  uniqueTechnologyNames,
} from "../lib/technology-icons";

test("requested brand aliases resolve to real local assets", () => {
  const aliases = new Map([
    ["GPT-5", "openai"], ["Claude", "anthropic"], ["Gemini 2.5", "googlegemini"],
    ["Hugging Face", "huggingface"], ["LangChain", "langchain"],
    ["PyTorch", "pytorch"], ["TensorFlow", "tensorflow"],
    ["Pinecone", "pinecone"], ["Weaviate", "weaviate"], ["Qdrant", "qdrant"],
    ["Amazon Web Services", "aws"], ["Google Cloud Platform", "googlecloud"],
    ["Microsoft Azure", "azure"], ["Docker", "docker"],
    ["K8s", "kubernetes"],
  ]);

  for (const [name, asset] of aliases) {
    assert.equal(technologyIconFor(name)?.asset, asset, name);
    assert.doesNotThrow(() => readFileSync(new URL(`../public/tech/${asset}.svg`, import.meta.url)));
  }
});

test("concepts and unsupported identities stay text instead of borrowing a logo", () => {
  for (const concept of ["Generative AI", "LLMs", "AI agents", "Machine learning", "LLM API", "Vector databases", "RAG"]) {
    assert.equal(technologyKind(concept), "concept", concept);
    assert.equal(technologyIconFor(concept), null, concept);
  }
  assert.equal(technologyKind("pgvector"), "text");
  assert.equal(technologyIconFor("pgvector"), null);
  assert.equal(technologyKind("Private framework"), "text");
});

test("chip window trims, deduplicates, caps four, expands, and collapses", () => {
  const names = [" React ", "GPT", "react", "RAG", "pgvector", "Qdrant"];
  assert.deepEqual(uniqueTechnologyNames(names), ["React", "GPT", "RAG", "pgvector", "Qdrant"]);
  assert.deepEqual(technologyChipWindow(names, 4, false), {
    visibleNames: ["React", "GPT", "RAG", "pgvector"],
    hiddenCount: 1,
    collapsedLimit: 4,
  });
  assert.deepEqual(technologyChipWindow(names, 4, true), {
    visibleNames: ["React", "GPT", "RAG", "pgvector", "Qdrant"],
    hiddenCount: 0,
    collapsedLimit: 4,
  });
});

test("provenance covers every added asset with matching bytes and safe SVGs", () => {
  const provenance = JSON.parse(readFileSync(
    new URL("../public/tech/PROVENANCE.json", import.meta.url), "utf8",
  ));
  assert.equal(provenance.version, 1);
  assert.equal(provenance.assets.length, 13);
  for (const entry of provenance.assets) {
    const bytes = readFileSync(new URL(`../public/tech/${entry.file}`, import.meta.url));
    const text = bytes.toString("utf8");
    assert.equal(createHash("sha256").update(bytes).digest("hex"), entry.sha256);
    assert.match(entry.source, /^https:\/\//);
    assert.doesNotMatch(text, /<script|<foreignObject|<!DOCTYPE|xlink:href|javascript:|data:|<image|\son[a-z]+\s*=/i);
    assert.doesNotMatch(text, /\shref\s*=\s*["'](?!#)/i);
    assert.doesNotMatch(text, /url\((?!\s*["']?#)/i);
  }
});
