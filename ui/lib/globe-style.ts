import type { MapOptions } from "maplibre-gl";
let styleRequest: Promise<MapOptions["style"]> | null = null;
export function loadGlobeStyle(): Promise<MapOptions["style"]> {
  if (!styleRequest) {
    styleRequest = fetch("https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json")
      .then(response => { if (!response.ok) throw new Error(`Map style: ${response.status}`); return response.json(); })
      .then(body => ({ ...(body as object), projection: { type: "globe" } }) as MapOptions["style"])
      .catch(error => { styleRequest = null; throw error; });
  }
  return styleRequest;
}
