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

export type PostingDateKind = "posted" | "republished" | "published" | "found";
export type PostingDate = { kind: PostingDateKind; short: string; tooltip: string; label: string; dateTime: string };

function parsedTime(value: string | null | undefined): number | null {
  if (!value) return null;
  const time = Date.parse(value);
  return Number.isFinite(time) ? time : null;
}

function compactAge(time: number, now: number): string {
  const hours = Math.max(0, Math.floor((now - time) / 3_600_000));
  return hours < 1 ? "now" : hours < 24 ? `${hours}h` : `${Math.floor(hours / 24)}d`;
}

function spokenAge(time: number, now: number): string {
  const hours = Math.max(0, Math.floor((now - time) / 3_600_000));
  if (hours < 1) return "just now";
  const [count, unit] = hours < 24 ? [hours, "hour"] : [Math.floor(hours / 24), "day"];
  return `${count} ${unit}${count === 1 ? "" : "s"} ago`;
}

// ISO-style calendar date (and optional 24h time) in the viewer's zone, or `timeZone` when given.
function calendarStamp(time: number, timeZone: string | undefined, withTime: boolean): string {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-CA", { timeZone, year: "numeric", month: "2-digit", day: "2-digit",
    ...(withTime ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" } : {}) }).formatToParts(time).map(part => [part.type, part.value]));
  const date = `${parts.year}-${parts.month}-${parts.day}`;
  return withTime ? `${date} ${parts.hour}:${parts.minute}` : date;
}

function isRepublished(posted: number | null, latest: number | null): boolean {
  return posted !== null && latest !== null && latest > posted;
}

export function postingDates(postedAt: string | null, firstSeenAt: string | null, now = Date.now(), lastPublishedAt: string | null = null, timeZone?: string): PostingDate[] {
  const posted = parsedTime(postedAt), latest = parsedTime(lastPublishedAt), found = parsedTime(firstSeenAt);
  const dates: PostingDate[] = [];
  const add = (kind: PostingDateKind, time: number, value: string, tooltip: string) =>
    dates.push({ kind, short: compactAge(time, now), tooltip, label: `${tooltip}, ${spokenAge(time, now)}`, dateTime: value });
  if (posted !== null) add("posted", posted, postedAt!, `Posted ${calendarStamp(posted, timeZone, false)}`);
  if (latest !== null && isRepublished(posted, latest)) add("republished", latest, lastPublishedAt!, `Republished ${calendarStamp(latest, timeZone, false)}`);
  else if (latest !== null && posted === null) add("published", latest, lastPublishedAt!, `Published ${calendarStamp(latest, timeZone, false)}`);
  if (found !== null) add("found", found, firstSeenAt!, `Found by JRC ${calendarStamp(found, timeZone, true)}`);
  return dates;
}

export function repostNote(postedAt: string | null, lastPublishedAt: string | null | undefined, earlierListings: number, timeZone?: string): string | null {
  const latest = parsedTime(lastPublishedAt);
  const notes = [];
  if (latest !== null && isRepublished(parsedTime(postedAt), latest)) notes.push(`republished ${calendarStamp(latest, timeZone, false)}`);
  if (earlierListings > 0) notes.push(`${earlierListings} earlier listing${earlierListings === 1 ? "" : "s"} of this role`);
  return notes.length ? `Reposted: ${notes.join(" · ")}` : null;
}

export function workMode(remote: boolean | null): string {
  return remote === true ? "Remote" : remote === false ? "On-site" : "Work mode unspecified";
}
