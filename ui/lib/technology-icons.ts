export type TechnologyIcon = {
  asset: string;
  color: string;
  wide?: boolean;
};

const BRAND_ICONS: Record<string, TechnologyIcon> = {
  react: { asset: "react", color: "#149eca" },
  "react native": { asset: "react", color: "#149eca" },
  typescript: { asset: "typescript", color: "#3178c6" },
  javascript: { asset: "javascript", color: "#c9ae08" },
  "next.js": { asset: "nextdotjs", color: "currentColor" },
  nextjs: { asset: "nextdotjs", color: "currentColor" },
  "node.js": { asset: "nodedotjs", color: "#5fa04e" },
  nodejs: { asset: "nodedotjs", color: "#5fa04e" },
  python: { asset: "python", color: "#3776ab" },
  postgresql: { asset: "postgresql", color: "#4169a1" },
  postgres: { asset: "postgresql", color: "#4169a1" },
  docker: { asset: "docker", color: "#2496ed" },
  kubernetes: { asset: "kubernetes", color: "#326ce5" },
  k8s: { asset: "kubernetes", color: "#326ce5" },
  go: { asset: "go", color: "#00add8" },
  golang: { asset: "go", color: "#00add8" },
  vue: { asset: "vuedotjs", color: "#42b883" },
  "vue.js": { asset: "vuedotjs", color: "#42b883" },
  angular: { asset: "angular", color: "#dd0031" },
  openai: { asset: "openai", color: "currentColor" },
  chatgpt: { asset: "openai", color: "currentColor" },
  anthropic: { asset: "anthropic", color: "currentColor" },
  claude: { asset: "anthropic", color: "#d97757" },
  gemini: { asset: "googlegemini", color: "#8e75b2" },
  "google gemini": { asset: "googlegemini", color: "#8e75b2" },
  "hugging face": { asset: "huggingface", color: "#d9a400" },
  huggingface: { asset: "huggingface", color: "#d9a400" },
  langchain: { asset: "langchain", color: "#1c3c3c" },
  pytorch: { asset: "pytorch", color: "#ee4c2c" },
  tensorflow: { asset: "tensorflow", color: "#ff6f00" },
  pinecone: { asset: "pinecone", color: "#0b8f79", wide: true },
  weaviate: { asset: "weaviate", color: "#00a98f" },
  qdrant: { asset: "qdrant", color: "#dc244c" },
  aws: { asset: "aws", color: "#ff9900", wide: true },
  "amazon web services": { asset: "aws", color: "#ff9900", wide: true },
  gcp: { asset: "googlecloud", color: "#4285f4" },
  "google cloud": { asset: "googlecloud", color: "#4285f4" },
  "google cloud platform": { asset: "googlecloud", color: "#4285f4" },
  azure: { asset: "azure", color: "#0078d4" },
  "microsoft azure": { asset: "azure", color: "#0078d4" },
  "microsoft cloud": { asset: "azure", color: "#0078d4" },
};

const CONCEPT_TERMS = new Set([
  "generative ai", "genai", "llm", "llms", "large language model",
  "large language models", "ai agent", "ai agents", "agentic ai",
  "machine learning", "llm api", "llm apis", "vector database",
  "vector databases", "rag", "retrieval augmented generation",
]);

export function normalizedTechnologyName(name: string): string {
  return name.trim().replace(/\s+/g, " ").toLocaleLowerCase("en-US");
}

export function technologyIconFor(name: string): TechnologyIcon | null {
  const normalized = normalizedTechnologyName(name);
  if (/^gpt(?:\b|[- .]?\d)/.test(normalized)) return BRAND_ICONS.openai;
  if (/^claude(?:\b|[- .]?\d)/.test(normalized)) return BRAND_ICONS.claude;
  if (/^gemini(?:\b|[- .]?\d)/.test(normalized)) return BRAND_ICONS.gemini;
  return BRAND_ICONS[normalized] ?? null;
}

export function technologyKind(name: string): "brand" | "concept" | "text" {
  if (technologyIconFor(name)) return "brand";
  return CONCEPT_TERMS.has(normalizedTechnologyName(name)) ? "concept" : "text";
}

export function uniqueTechnologyNames(names: readonly string[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  for (const raw of names) {
    const name = raw.trim().replace(/\s+/g, " ");
    const key = normalizedTechnologyName(name);
    if (!key || seen.has(key)) continue;
    seen.add(key);
    result.push(name);
  }
  return result;
}

export function technologyChipWindow(
  names: readonly string[], limit: number, expanded: boolean,
): { visibleNames: string[]; hiddenCount: number; collapsedLimit: number } {
  const allNames = uniqueTechnologyNames(names);
  const collapsedLimit = Number.isFinite(limit) ? Math.max(1, Math.trunc(limit)) : 4;
  return {
    visibleNames: expanded ? allNames : allNames.slice(0, collapsedLimit),
    hiddenCount: expanded ? 0 : Math.max(0, allNames.length - collapsedLimit),
    collapsedLimit,
  };
}
