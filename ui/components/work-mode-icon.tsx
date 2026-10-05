import { Building2, FileQuestionMark, MonitorCloud, ScreenShare, type LucideIcon } from "lucide-react";
import { workModeOf, type WorkModeKind } from "@/lib/job-display";
import { cn } from "@/lib/utils";

// Building2 is lucide's building-complex: the same glyph, renamed upstream after the lucide-react we ship.
const icons: Record<WorkModeKind, LucideIcon> = { remote: MonitorCloud, "on-site": Building2, hybrid: ScreenShare, unknown: FileQuestionMark };

/** The work mode as an icon named by its text; `showLabel` prints the text beside it instead. */
export function WorkModeIcon({ job, showLabel = false, size = 15, className }: { job: Parameters<typeof workModeOf>[0]; showLabel?: boolean; size?: number; className?: string }) {
  const { kind, label } = workModeOf(job);
  const Icon = icons[kind];
  if (showLabel) return <span data-work-mode={kind} className={cn("inline-flex items-center gap-1", className)}><Icon aria-hidden="true" size={size} className="shrink-0" />{label}</span>;
  return <span data-work-mode={kind} role="img" aria-label={label} title={label} className={cn("inline-flex shrink-0", className)}><Icon aria-hidden="true" size={size} /></span>;
}
