import { postingDates } from "@/lib/job-display";

type Props = {
  postedAt: string | null;
  firstSeenAt: string | null;
  now?: number;
  className?: string;
};

export function PostingDates({ postedAt, firstSeenAt, now, className }: Props) {
  const dates = postingDates(postedAt, firstSeenAt, now);
  return <span className={className}>{dates.map((date, index) =>
    <span key={date.label}>{index > 0 ? " · " : null}<time dateTime={date.dateTime} title={date.dateTime}>{date.label}</time></span>
  )}</span>;
}
