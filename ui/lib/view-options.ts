// SQL board_postings mirrors these values and the good-fit threshold; changes need SQL parity checks.
export const foundWithinOptions = [
  { value: "", label: "Any time", days: null },
  { value: "24h", label: "24 h", days: 1 },
  { value: "3d", label: "3 d", days: 3 },
  { value: "7d", label: "7 d", days: 7 },
  { value: "30d", label: "30 d", days: 30 },
] as const;
export const fitOptions = [
  { value: "", label: "Any fit" }, { value: "recommended", label: "Worth considering" },
  { value: "skip", label: "Suggested skip" }, { value: "good", label: "60+ fit score" },
  { value: "scored", label: "Scored" }, { value: "unscored", label: "Not scored" },
] as const;
export const sortOptions = [
  { value: "found", label: "Recently found" }, { value: "posted", label: "Recently posted" },
  { value: "fit", label: "Best fit first" }, { value: "seniority", label: "Seniority: junior first" },
] as const;
export const GOOD_FIT_SCORE = 60;
export type FoundWithin = typeof foundWithinOptions[number]["value"];
export type JobSort = typeof sortOptions[number]["value"];
export function foundWithinCutoff(window: FoundWithin | undefined, now = Date.now()): number | null {
  const days = foundWithinOptions.find(option => option.value === window)?.days;
  return days === null || days === undefined ? null : now - days * 86_400_000;
}
