import { CalendarPlus, Plus, Recycle, Search, type LucideIcon } from "lucide-react";
import { postingDates, type PostingDateKind } from "@/lib/job-display";
import { cn } from "@/lib/utils";
import { InfoTip } from "./info-tip";

type Props = {
  postedAt: string | null;
  lastPublishedAt?: string | null;
  firstSeenAt: string | null;
  now?: number;
  timeZone?: string;
  className?: string;
  /** `calendar-plus` is the unambiguous alternative to a bare plus, kept for side-by-side comparison. */
  postedIcon?: "plus" | "calendar-plus";
  /** Static mode renders no buttons, for use inside another interactive element. */
  interactive?: boolean;
};

const icons: Record<PostingDateKind, LucideIcon> = { posted: Plus, published: Plus, republished: Recycle, found: Search };

export function PostingDates({ postedAt, lastPublishedAt = null, firstSeenAt, now, timeZone, className, postedIcon = "plus", interactive = true }: Props) {
  const dates = postingDates(postedAt, firstSeenAt, now, lastPublishedAt, timeZone);
  return <span data-posting-dates className={cn("inline-flex flex-wrap items-center gap-x-2 gap-y-0.5", className)}>
    {dates.length === 0 ? "Date unavailable" : dates.map(date => {
      const Icon = postedIcon === "calendar-plus" && icons[date.kind] === Plus ? CalendarPlus : icons[date.kind];
      const icon = <Icon aria-hidden="true" size={12} strokeWidth={2.25} className="shrink-0" />;
      return interactive
        ? <InfoTip key={date.kind} data-date-kind={date.kind} label={date.label} tip={date.tooltip}>{icon}<time dateTime={date.dateTime}>{date.short}</time></InfoTip>
        : <span key={date.kind} data-date-kind={date.kind} title={date.tooltip} className="inline-flex items-center gap-0.5 tabular-nums">
          {icon}<time aria-hidden="true" dateTime={date.dateTime}>{date.short}</time><span className="sr-only">{date.label}</span>
        </span>;
    })}
  </span>;
}
