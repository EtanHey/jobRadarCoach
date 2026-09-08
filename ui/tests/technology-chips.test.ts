import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

import {
  technologyChipWindow,
  technologyIconFor,
  technologyKind,
  uniqueTechnologyNames,
} from "../lib/technology-icons";

test("requested brand aliases resolve to real local assets", () => {
  const aliases = new Map([
    ["GraphQL", "graphql"], ["GPT-5", "openai"], ["Codex", "openai"],
    ["Claude", "claude"], ["Claude Code", "claudecode"], ["Gemini 2.5", "googlegemini"],
    ["Hugging Face", "huggingface"], ["LangChain", "langchain"],
    ["PyTorch", "pytorch"], ["TensorFlow", "tensorflow"],
    ["Pinecone", "pinecone"], ["Weaviate", "weaviate"], ["Qdrant", "qdrant"],
    ["Amazon Web Services", "aws"], ["Google Cloud Platform", "googlecloud"],
    ["Microsoft Azure", "azure"], ["Docker", "docker"],
    ["K8s", "kubernetes"], ["Java", "java"], ["C++", "cplusplus"],
    ["Git", "git"], ["Terraform", "terraform"], ["Kafka", "apachekafka"],
    ["Linux", "linux"], ["Redis", "redis"], ["MySQL", "mysql"],
    ["MongoDB", "mongodb"], ["Rust", "rust"], ["C#", "csharp"],
    ["GitHub Actions", "githubactions"], ["HTML", "html5"], ["CSS", "css"],
    ["RabbitMQ", "rabbitmq"], ["LangGraph", "langgraph"],
    ["OpenTelemetry", "opentelemetry"], ["Snowflake", "snowflake"],
    ["Helm", "helm"], ["Prometheus", "prometheus"], ["Spark", "apachespark"],
    ["C", "c"], ["Elasticsearch", "elasticsearch"], ["FastAPI", "fastapi"],
    ["Grafana", "grafana"], ["JSON", "json"], ["Scala", "scala"],
    ["Spring Boot", "springboot"],
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
  for (const ambiguous of ["Apollo", "Make", "NX", "ELK", "RTL", "Radar", "shell", "less", "SolidWorks"]) {
    assert.equal(technologyKind(ambiguous), "text", ambiguous);
    assert.equal(technologyIconFor(ambiguous), null, ambiguous);
  }
  for (const catalogMiss of ["S3", "EC2", "Lambda"]) {
    assert.equal(technologyKind(catalogMiss), "text", catalogMiss);
    assert.equal(technologyIconFor(catalogMiss), null, catalogMiss);
  }
});

test("near-black monochrome marks inherit readable foreground color", () => {
  for (const name of ["GitHub", "Bash", "Express", "Django", "Anthropic", "Kafka"]) {
    assert.equal(technologyIconFor(name)?.color, "currentColor", name);
  }
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
  assert.equal(provenance.catalogs.simple_icons.revision, "777807a262bb7384ff406fd4b35fdcd02e9514c3");
  assert.equal(provenance.catalogs.devicon.revision, "v2.17.0");
  const svgFiles = readdirSync(new URL("../public/tech/", import.meta.url))
    .filter((file) => file.endsWith(".svg")).sort();
  assert.deepEqual(provenance.assets.map((entry: { file: string }) => entry.file).sort(), svgFiles);
  for (const entry of provenance.assets) {
    const bytes = readFileSync(new URL(`../public/tech/${entry.file}`, import.meta.url));
    const text = bytes.toString("utf8");
    assert.match(text, /^\s*(?:<\?xml[^>]*>\s*)?<svg\b/i, entry.file);
    assert.equal(createHash("sha256").update(bytes).digest("hex"), entry.sha256);
    assert.match(entry.source, /^https:\/\//);
    assert.doesNotMatch(text, /<script|<foreignObject|<!DOCTYPE|xlink:href|javascript:|data:|<image|\son[a-z]+\s*=/i);
    assert.doesNotMatch(text, /\shref\s*=\s*["'](?!#)/i);
    assert.doesNotMatch(text, /url\((?!\s*["']?#)/i);
  }
});

test("non-CC0 Simple Icons assets have pinned attribution and exact notices", () => {
  const directory = new URL("../public/tech/", import.meta.url);
  const provenance = JSON.parse(readFileSync(new URL("PROVENANCE.json", directory), "utf8"));
  const attribution = JSON.parse(readFileSync(
    new URL("SIMPLE-ICONS-ATTRIBUTION.json", directory), "utf8",
  ));
  const expected = provenance.assets.filter(
    (entry: { source_kind: string; license: string }) =>
      entry.source_kind === "Simple Icons" && entry.license !== "CC0-1.0",
  );
  assert.equal(attribution.simple_icons_revision, provenance.catalogs.simple_icons.revision);
  assert.equal(attribution.license_metadata_source,
    provenance.catalogs.simple_icons.license_metadata_source);
  assert.deepEqual(attribution.assets.map((entry: { file: string }) => entry.file).sort(),
    expected.map((entry: { file: string }) => entry.file).sort());
  for (const entry of attribution.assets) {
    const source = expected.find((candidate: { file: string }) => candidate.file === entry.file);
    assert.equal(entry.identity, source.identity, entry.file);
    assert.equal(entry.license, source.license, entry.file);
    assert.match(entry.attribution, /\S/, entry.file);
    assert.match(entry.license_url, /^https:\/\//, entry.file);
    assert.match(entry.upstream_source, /^https:\/\//, entry.file);
    assert.equal(entry.modifications,
      "None; local bytes match the pinned Simple Icons SVG.", entry.file);
    if (["MIT", "Apache-2.0"].includes(entry.license)) {
      assert.doesNotThrow(() => readFileSync(new URL(entry.notice, directory)), entry.file);
    }
  }
  const vue = attribution.assets.find((entry: { file: string }) => entry.file === "vuedotjs.svg");
  assert.equal(vue.license, "CC-BY-NC-SA-4.0");
  assert.match(vue.restrictions, /NonCommercial.*ShareAlike.*not unrestricted/);
  const summary = readFileSync(new URL("LICENSE.txt", directory), "utf8");
  assert.match(summary, /does not imply every included\s+icon is CC0/);
  assert.match(summary, /other 20 Simple Icons assets have per-asset license links/);

  const noticeHashes = new Map([
    ["DEVICON-LICENSE.txt", "121194741d4a915b9f5890fdd6dd95121f9b1f816517c792358d72d7c838d664"],
    ["OPENAI-COOKBOOK-LICENSE.txt", "13df7812ca53ecaae1cb4a868844bb598373047ae1d580e4debfbef1dd5b6915"],
    ["APACHE-2.0-LICENSE.txt", "eeaab2b71a230ef2e9b7c0a985c095bc442295e822274c7fa039301c953ed73e"],
    ["GITHUB-OCTICONS-LICENSE.txt", "da259c8bd0de62713ccdcf88910aebca810644f98c2c912bad814fc79ea778df"],
    ["LOGO-JS-LICENSE.txt", "0d3f7c086c6b6cf3ea4aac714e9aa3e1fb02e355ce35bd21c56acf8d04390885"],
    ["SANITY-LOGOS-LICENSE.txt", "96654880788193a7aee237786f058f19704018854164d9b2ce1fb8f25a6b6c8e"],
    ["STORYBOOK-BRAND-LICENSE.txt", "9e6bd0d36df5bab977b665533151e0a6ddd81e6a64fb21a33213216d1e2d08ad"],
  ]);
  for (const [file, hash] of noticeHashes) {
    const bytes = readFileSync(new URL(file, directory));
    assert.equal(createHash("sha256").update(bytes).digest("hex"), hash, file);
  }
});
