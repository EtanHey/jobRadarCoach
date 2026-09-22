import type { DuplicateJobGroup } from "./job-dedup";
import type { GlobePoint } from "./globe-model";

type ScreenPoint = { x: number; y: number };
type Coordinate = { lng: number; lat: number };
// Round-trip projection rejects the far hemisphere even when its projected pixel is in bounds.
export function viewportPostingIds(points: GlobePoint[], width: number, height: number,
  project: (point: GlobePoint) => ScreenPoint, unproject: (screen: ScreenPoint) => Coordinate): string[] {
  if (width <= 0 || height <= 0) return [];
  const visible: string[] = [];
  for (const point of points) {
    if (point.job.alive === false) continue;
    const screen = project(point);
    if (!Number.isFinite(screen.x) || !Number.isFinite(screen.y) || screen.x < 0 || screen.y < 0 || screen.x > width || screen.y > height) continue;
    const back = unproject(screen);
    const longitudeDelta = Math.abs(((back.lng - point.lng + 540) % 360) - 180);
    if (longitudeDelta <= 0.01 && Math.abs(back.lat - point.lat) <= 0.01) visible.push(point.posting_id);
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
