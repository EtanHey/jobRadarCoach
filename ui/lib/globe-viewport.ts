import type { DuplicateJobGroup } from "./job-dedup";
import type { GlobePoint } from "./globe-model";

type ScreenPoint = { x: number; y: number };
type Coordinate = { lng: number; lat: number };
export type Bounds = [[number, number], [number, number]];
export const LOCATION_BOUNDS: Record<"israel" | "united-states", Bounds> = {
  israel: [[34.20, 29.45], [35.90, 33.35]],
  "united-states": [[-125.0, 24.4], [-66.9, 49.4]],
};
export function locationCameraBounds(location: string, points: readonly Coordinate[]): Bounds | null {
  if (location === "israel" || location === "united-states") return LOCATION_BOUNDS[location];
  if (location !== "other" || points.length === 0) return null;
  const lng = points.map(point => point.lng), lat = points.map(point => point.lat);
  const west = Math.min(...lng), east = Math.max(...lng);
  return east - west < 150 ? [[west, Math.min(...lat)], [east, Math.max(...lat)]] : null;
}
export function focusPointCamera({ zoom, width, height, coveredRight, x, y }: {
  zoom: number; width: number; height: number; coveredRight: number; x: number; y: number;
}): { zoom: number; offsetX: number } | null {
  const visibleWidth = Math.max(1, width - coveredRight);
  if (zoom >= 5 && x >= visibleWidth * .2 && x <= visibleWidth * .8 && y >= height * .2 && y <= height * .8) return null;
  return { zoom: Math.max(zoom, 5), offsetX: coveredRight ? -coveredRight / 2 : 0 };
}
export function cameraNeedsReset(center: [number, number], zoom: number, home: [number, number], homeZoom: number): boolean {
  return Math.abs(center[0] - home[0]) > 1 || Math.abs(center[1] - home[1]) > 1 || Math.abs(zoom - homeZoom) > .25;
}
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
