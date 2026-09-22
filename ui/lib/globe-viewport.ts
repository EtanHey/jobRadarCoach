import type { DuplicateJobGroup } from "./job-dedup";
import type { GlobePoint } from "./globe-model";

type ScreenPoint = { x: number; y: number };
type Coordinate = { lng: number; lat: number };
export function usableMapSize(width: number, height: number): boolean {
  return Number.isFinite(width) && Number.isFinite(height) && width > 0 && height > 0;
}
// Round-trip projection rejects the far hemisphere even when its projected pixel is in bounds.
export function viewportPostingIds(points: GlobePoint[], width: number, height: number,
  project: (point: GlobePoint) => ScreenPoint, unproject: (screen: ScreenPoint) => Coordinate): string[] {
  if (!usableMapSize(width, height)) return [];
  const visible: string[] = [];
  for (const point of points) {
    if (point.job.alive === false) continue;
    try {
      const screen = project(point);
      if (!Number.isFinite(screen.x) || !Number.isFinite(screen.y) || screen.x < 0 || screen.y < 0 || screen.x > width || screen.y > height) continue;
      const back = unproject(screen);
      if (!Number.isFinite(back.lng) || !Number.isFinite(back.lat)) continue;
      const longitudeDelta = Math.abs(((back.lng - point.lng + 540) % 360) - 180);
      if (longitudeDelta <= 0.01 && Math.abs(back.lat - point.lat) <= 0.01) visible.push(point.posting_id);
    } catch (error) {
      // A camera transition can make MapLibre's projection briefly invalid.
      if (!(error instanceof Error) || !error.message.includes("Invalid LngLat")) throw error;
    }
  }
  return visible;
}
// A role is visible when any available listing in its existing dedup group is on screen.
export function partitionGlobeGroups(groups: DuplicateJobGroup[], visiblePostingIds: readonly string[]) {
  const ids = new Set(visiblePostingIds);
  const visible: DuplicateJobGroup[] = [], outside: DuplicateJobGroup[] = [];
  for (const group of groups) {
    const onScreen = [group.job, ...group.alternates].some(job => job.alive !== false && ids.has(job.id));
    (onScreen ? visible : outside).push(group);
  }
  return { visible, outside };
}
export function countGlobeRoles(groups: DuplicateJobGroup[], points: GlobePoint[]) {
  const mappedIds = new Set(points.map(point => point.posting_id));
  const mapped = groups.filter(group => [group.job, ...group.alternates].some(job => mappedIds.has(job.id))).length;
  return { total: groups.length, mapped, unmapped: groups.length - mapped };
}
