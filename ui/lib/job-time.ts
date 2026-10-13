/** Missing or invalid chronology is null; callers choose their sorting fallback. */
export function timestamp(value: string | null | undefined): number | null {
  if (!value) return null;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? null : parsed;
}
