import type { JobSummary } from "./contracts";
import type { DuplicateJobGroup } from "./job-dedup";

export type PostingPoint = { posting_id: string; lat: number; lng: number; precision: "city" | "region" | "country" | "hq"; source: string; resolved_at: string };
export type GlobePoint = PostingPoint & { job: JobSummary; rowId: string };
export const FALLBACK_CENTER: [number, number] = [34.8113, 31.8928];
export function globePoints(groups: DuplicateJobGroup[], coordinates: PostingPoint[]): GlobePoint[] {
  const rows = new Map<string, { job: JobSummary; rowId: string }>();
  for (const group of groups) for (const job of [group.job, ...group.alternates]) rows.set(job.id, { job, rowId: group.job.id });
  return coordinates.flatMap(point => {
    const row = rows.get(point.posting_id);
    return row && Number.isFinite(point.lat) && Math.abs(point.lat) <= 90 && Number.isFinite(point.lng) && Math.abs(point.lng) <= 180 ? [{ ...point, ...row }] : [];
  });
}
// Bound GPU work without moving a posting away from its real coordinate.
export function thinPoints(points: GlobePoint[], selected: string | null, limit = 5000): GlobePoint[] {
  if (points.length <= limit) return points;
  const chosen = points.find(point => point.posting_id === selected);
  const stride = Math.ceil(points.length / (limit - 1));
  const sampled = points.filter((point, index) => index % stride === 0 && point !== chosen);
  return chosen ? [chosen, ...sampled].slice(0, limit) : sampled.slice(0, limit);
}
export function scoreColor(score: number | null): [number, number, number, number] {
  return score === null ? [148, 163, 184, 255] : score >= 80 ? [52, 211, 153, 255] : score >= 60 ? [56, 189, 248, 255] : [251, 191, 36, 255];
}
export function pointLabel(point: GlobePoint): string {
  return point.precision === "hq" ? "Company HQ · not the job location" : `Approximate ${point.precision} location`;
}

export const scoreBands = [{ score: 80, label: "80–100" }, { score: 60, label: "60–79" }, { score: 0, label: "Below 60" }, { score: null, label: "Unscored" }];
export const scoreCss = (score: number | null) => `rgb(${scoreColor(score).slice(0, 3).join(",")})`;

export type PointCluster = { anchor: GlobePoint; members: GlobePoint[] };
// Screen collisions share a real member coordinate; no geospatial jitter is invented.
export function clusterPoints(points: GlobePoint[], project: (point: GlobePoint) => { x: number; y: number } | null, radius = 32): PointCluster[] {
  const cells = new Map<string, { x: number; y: number; cluster: PointCluster }[]>();
  const clusters: PointCluster[] = [];
  for (const point of points) {
    const screen = project(point);
    if (!screen || !Number.isFinite(screen.x) || !Number.isFinite(screen.y)) continue;
    const cx = Math.floor(screen.x / radius), cy = Math.floor(screen.y / radius);
    let target: PointCluster | undefined;
    for (let x = cx - 1; x <= cx + 1 && !target; x++) for (let y = cy - 1; y <= cy + 1 && !target; y++) {
      target = cells.get(`${x},${y}`)?.find(cell => Math.hypot(cell.x - screen.x, cell.y - screen.y) < radius)?.cluster;
    }
    if (target) target.members.push(point);
    else {
      const cluster = { anchor: point, members: [point] };
      clusters.push(cluster);
      const key = `${cx},${cy}`;
      cells.set(key, [...(cells.get(key) ?? []), { ...screen, cluster }]);
    }
  }
  return clusters;
}
// A cluster uses the best existing member score. Individual scores never change.
export const clusterScore = (cluster: PointCluster) => cluster.members.reduce<number | null>((best, point) => point.job.score === null ? best : Math.max(best ?? 0, point.job.score), null);

export function globeChoices(points: GlobePoint[], choiceIds: string[]): GlobePoint[] {
  if (!choiceIds.length) return [];
  const byId = new Map<string, GlobePoint[]>();
  for (const point of points) {
    const id = point.posting_id;
    const matches = byId.get(id);
    if (matches) matches.push(point);
    else byId.set(id, [point]);
  }
  return choiceIds.flatMap(id => byId.get(id) ?? []);
}
