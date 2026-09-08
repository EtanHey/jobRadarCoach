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

export function workMode(remote: boolean | null): string {
  return remote === true ? "Remote" : remote === false ? "On-site" : "Work mode unspecified";
}
