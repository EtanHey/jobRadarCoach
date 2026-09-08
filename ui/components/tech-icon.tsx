import { Code2 } from "lucide-react";

const icons: Record<string, [string, string]> = {
  react: ["react", "#149eca"], "react native": ["react", "#149eca"],
  typescript: ["typescript", "#3178c6"], javascript: ["javascript", "#c9ae08"],
  "next.js": ["nextdotjs", "currentColor"], nextjs: ["nextdotjs", "currentColor"],
  "node.js": ["nodedotjs", "#5fa04e"], nodejs: ["nodedotjs", "#5fa04e"],
  python: ["python", "#3776ab"], postgresql: ["postgresql", "#4169a1"],
  postgres: ["postgresql", "#4169a1"], docker: ["docker", "#2496ed"],
  kubernetes: ["kubernetes", "#326ce5"], go: ["go", "#00add8"],
  vue: ["vuedotjs", "#42b883"], "vue.js": ["vuedotjs", "#42b883"], angular: ["angular", "#dd0031"],
};

export function TechIcon({ name }: { name: string }) {
  const icon = icons[name.toLowerCase()];
  return icon ? <span aria-hidden="true" className="inline-block size-3.5 shrink-0" style={{
    backgroundColor: icon[1], maskImage: `url(/tech/${icon[0]}.svg)`,
    maskSize: "contain", maskRepeat: "no-repeat", maskPosition: "center",
  }} /> : <Code2 size={14} aria-hidden="true" />;
}
