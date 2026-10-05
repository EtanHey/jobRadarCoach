export function relativeAge(value: string | null, now = Date.now()): string | null {
  if (!value) return null;
  const time = Date.parse(value);
  if (!Number.isFinite(time)) return null;
  const hours = Math.max(0, Math.floor((now - time) / 3_600_000));
  return hours < 1 ? "just now" : hours < 24 ? `${hours}h ago` : `${Math.floor(hours / 24)}d ago`;
}

export function publishedAge(value: string | null, now = Date.now()): string {
  const age = relativeAge(value, now);
  return age ? `Posted ${age}` : "Posted date unavailable";
}

type PostingDate = { label: string; dateTime: string | undefined };

export function postingDates(postedAt: string | null, firstSeenAt: string | null, now = Date.now()): PostingDate[] {
  const posted = relativeAge(postedAt, now);
  const found = relativeAge(firstSeenAt, now);
  const dates: PostingDate[] = [];
  if (posted) dates.push({ label: `Posted ${posted}`, dateTime: postedAt ?? undefined });
  if (found) dates.push({ label: `Found ${found}`, dateTime: firstSeenAt ?? undefined });
  return dates.length ? dates : [{ label: "Date unavailable", dateTime: undefined }];
}

export type WorkModeKind = "remote" | "on-site" | "hybrid" | "unknown";
const workModeLabels: Record<WorkModeKind, string> = { remote: "Remote", "on-site": "On-site", hybrid: "Hybrid", unknown: "Work mode unspecified" };
const structuredWorkModes: Record<string, WorkModeKind> = { remote: "remote", hybrid: "hybrid", "on-site": "on-site", onsite: "on-site", on_site: "on-site", "on site": "on-site" };

/** A structured work mode (hybrid comes only from it) wins; otherwise the remote flag decides. */
export function workModeOf(job: { remote: boolean | null; work_mode?: string | null }): { kind: WorkModeKind; label: string } {
  const structured = job.work_mode?.trim().toLowerCase() ?? "";
  const kind = Object.hasOwn(structuredWorkModes, structured) ? structuredWorkModes[structured]
    : job.remote === true ? "remote" : job.remote === false ? "on-site" : "unknown";
  return { kind, label: workModeLabels[kind] };
}

export function workMode(remote: boolean | null): string {
  return workModeOf({ remote }).label;
}
