import type { ReactNode } from "react";

type InlineToken =
  | { kind: "text"; text: string }
  | { kind: "bold"; text: string }
  | { kind: "link"; label: string; href: string };

export type DescriptionBlock =
  | { kind: "heading"; level: number; text: string }
  | { kind: "paragraph"; text: string }
  | { kind: "list"; items: string[] };

export function isSafeDescriptionUrl(value: string): boolean {
  try {
    const url = new URL(value);
    return url.protocol === "http:" || url.protocol === "https:";
  } catch {
    return false;
  }
}

export function parseDescriptionBlocks(text: string): DescriptionBlock[] {
  const lines = text.replace(/\r\n?/g, "\n").split("\n");
  const blocks: DescriptionBlock[] = [];
  let index = 0;

  while (index < lines.length) {
    if (!lines[index].trim()) {
      index += 1;
      continue;
    }

    const heading = lines[index].match(/^(#{1,6})[ \t]+(.+)$/);
    if (heading) {
      blocks.push({ kind: "heading", level: heading[1].length, text: heading[2] });
      index += 1;
      continue;
    }

    const firstItem = lines[index].match(/^\s*[-*+]\s+(.+)$/);
    if (firstItem) {
      const items: string[] = [];
      while (index < lines.length) {
        const item = lines[index].match(/^\s*[-*+]\s+(.+)$/);
        if (!item) break;
        items.push(item[1]);
        index += 1;
      }
      blocks.push({ kind: "list", items });
      continue;
    }

    const paragraph: string[] = [];
    while (index < lines.length && lines[index].trim()) {
      if (paragraph.length > 0 && (/^(#{1,6})[ \t]+/.test(lines[index]) || /^\s*[-*+]\s+/.test(lines[index]))) break;
      paragraph.push(lines[index]);
      index += 1;
    }
    blocks.push({ kind: "paragraph", text: paragraph.join("\n") });
  }

  return blocks;
}

export function parseDescriptionInline(text: string): InlineToken[] {
  const tokens: InlineToken[] = [];
  const pattern = /(\*\*[^*\n]+\*\*|\[[^\]\n]+\]\(https?:\/\/[^\s)]+\))/gi;
  let cursor = 0;

  for (const match of text.matchAll(pattern)) {
    const start = match.index;
    if (start > cursor) tokens.push({ kind: "text", text: text.slice(cursor, start) });
    const value = match[0];
    if (value.startsWith("**")) {
      tokens.push({ kind: "bold", text: value.slice(2, -2) });
    } else {
      const split = value.indexOf("](");
      const label = value.slice(1, split);
      const href = value.slice(split + 2, -1);
      tokens.push(isSafeDescriptionUrl(href)
        ? { kind: "link", label, href }
        : { kind: "text", text: value });
    }
    cursor = start + value.length;
  }

  if (cursor < text.length) tokens.push({ kind: "text", text: text.slice(cursor) });
  return tokens;
}

function Inline({ text }: { text: string }) {
  return parseDescriptionInline(text).map((token, index): ReactNode => {
    if (token.kind === "bold") return <strong key={index} className="font-semibold text-foreground">{token.text}</strong>;
    if (token.kind === "link") return <a key={index} href={token.href} target="_blank" rel="noopener noreferrer" className="text-primary underline underline-offset-2 hover:no-underline">{token.label}</a>;
    return <span key={index}>{token.text}</span>;
  });
}

export function JobDescription({ text }: { text: string | null }) {
  if (!text?.trim()) {
    return <p className="text-sm leading-7 text-muted-foreground">No full description is available. Open the original posting for details.</p>;
  }

  return <div className="space-y-4 text-sm leading-7 text-muted-foreground">
    {parseDescriptionBlocks(text).map((block, index) => {
      if (block.kind === "heading") {
        const size = block.level <= 2 ? "text-base" : "text-sm";
        return <h3 key={index} className={`${size} font-semibold text-foreground`}><Inline text={block.text} /></h3>;
      }
      if (block.kind === "list") {
        return <ul key={index} className="list-disc space-y-1 pl-5">
          {block.items.map((item, itemIndex) => <li key={itemIndex}><Inline text={item} /></li>)}
        </ul>;
      }
      return <p key={index} className="whitespace-pre-line"><Inline text={block.text} /></p>;
    })}
  </div>;
}
