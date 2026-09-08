import { technologyIconFor } from "@/lib/technology-icons";

export function TechIcon({ name, className = "" }: {
  name: string;
  className?: string;
}) {
  const icon = technologyIconFor(name);
  if (!icon) return null;
  return <span
    aria-hidden="true"
    data-tech-icon={icon.asset}
    className={`inline-block h-3.5 shrink-0 ${icon.wide ? "w-5" : "w-3.5"} ${className}`}
    style={{
      backgroundColor: icon.color,
      maskImage: `url(/tech/${icon.asset}.svg)`,
      maskPosition: "center",
      maskRepeat: "no-repeat",
      maskSize: "contain",
    }}
  />;
}
