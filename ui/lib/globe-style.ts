import type { Map, MapOptions } from "maplibre-gl";

export type GlobeTheme = "light" | "dark";
type Paint = Record<string, unknown>;
type Layer = { id: string; type: string; paint?: Paint };
type GlobeStyle = { layers: Layer[]; sky?: Record<string, unknown>; projection?: { type: "globe" } } & Record<string, unknown>;
const urls: Record<GlobeTheme, string> = {
  light: "https://basemaps.cartocdn.com/gl/voyager-gl-style/style.json",
  dark: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json",
};
const requests: Partial<Record<GlobeTheme, Promise<GlobeStyle>>> = {};
export const activeGlobeTheme = (): GlobeTheme => document.documentElement.classList.contains("dark") ? "dark" : "light";
const colors = () => {
  const css = getComputedStyle(document.documentElement);
  const token = (name: string) => css.getPropertyValue(`--globe-${name}`).trim();
  return { space: token("space"), ocean: token("ocean"), land: token("land"), border: token("border"), label: token("label"), atmos: token("atmos") };
};
const sky = (color: ReturnType<typeof colors>): Parameters<Map["setSky"]>[0] => ({ "sky-color": color.atmos, "horizon-color": color.atmos, "fog-color": color.space,
  "atmosphere-blend": ["interpolate", ["linear"], ["zoom"], 0, 1, 5, 1, 7, 0] });
function overrides(layer: Layer, color: ReturnType<typeof colors>): Paint {
  const paint: Paint = {};
  if (layer.type === "background") paint["background-color"] = color.land;
  if (layer.type === "fill" && layer.id.startsWith("water")) paint["fill-color"] = color.ocean;
  if (layer.type === "fill" && /^(landcover|landuse)/.test(layer.id)) { paint["fill-color"] = color.land; paint["fill-opacity"] = .6; }
  if (layer.type === "line" && layer.id.startsWith("boundary_country")) { paint["line-color"] = color.border; paint["line-width"] = .8; }
  if (layer.type === "symbol" && /^(place_|country_)/.test(layer.id)) { paint["text-color"] = color.label; paint["text-halo-color"] = color.land; }
  if (layer.type === "symbol" && /^(roadname_|poi_)/.test(layer.id)) paint["text-opacity"] = ["step", ["zoom"], 0, 6, 1];
  return paint;
}
export function applyGlobePaint(map: Map) {
  const color = colors();
  map.setSky(sky(color));
  for (const layer of map.getStyle().layers) {
    for (const [key, value] of Object.entries(overrides(layer, color))) map.setPaintProperty(layer.id, key as Parameters<Map["setPaintProperty"]>[1], value as Parameters<Map["setPaintProperty"]>[2]);
  }
}
export function loadGlobeStyle(theme: GlobeTheme = activeGlobeTheme()): Promise<MapOptions["style"]> {
  requests[theme] ??= fetch(urls[theme])
    .then(response => { if (!response.ok) throw new Error(`Map style: ${response.status}`); return response.json() as Promise<GlobeStyle>; })
    .catch(error => { delete requests[theme]; throw error; });
  return requests[theme]!.then(source => {
    const style = structuredClone(source);
    const color = colors();
    style.projection = { type: "globe" };
    style.sky = sky(color);
    for (const layer of style.layers) layer.paint = { ...layer.paint, ...overrides(layer, color) };
    return style as MapOptions["style"];
  });
}
