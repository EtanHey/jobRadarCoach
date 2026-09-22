"use client";

import { useCallback, useEffect, useRef, useState, useMemo } from "react";
import { Map, NavigationControl, FullscreenControl, Marker, setWorkerUrl } from "maplibre-gl";
import { MapLibreOverlay } from "@deck.gl/maplibre";
import { ScatterplotLayer } from "@deck.gl/layers";
import { FALLBACK_CENTER, pointLabel, scoreColor, scoreCss, scoreBands, thinPoints, clusterPoints, clusterScore, globeChoices, type PointCluster, type GlobePoint } from "@/lib/globe-model";
import { viewportPostingIds } from "@/lib/globe-viewport";
import "maplibre-gl/dist/maplibre-gl.css";

setWorkerUrl(new URL("../lib/generated/maplibre-worker.mjs", import.meta.url).href);

function landingZoom(map: Map, latitude: number) {
  const edge = Math.min(map.getContainer().clientWidth, map.getContainer().clientHeight);
  // A hidden panel has no usable fit measurement; its first visible resize will cap this landing.
  if (edge <= 0) return 1.3;
  return Math.min(1.3, Math.log2(edge * Math.max(0.15, Math.cos(latitude * Math.PI / 180)) / 180));
}

type Props = { onViewportChange: (ids: string[]) => void; points: GlobePoint[]; selected: string | null; onSelect: (id: string) => void; onFailure: () => void };
export default function JobGlobe({ points, selected, onSelect, onFailure, onViewportChange }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const mapRef = useRef<Map | null>(null);
  const overlayRef = useRef<MapLibreOverlay | null>(null);
  const callbacks = useRef({ onSelect, onFailure, onViewportChange });
  const [clusters, setClusters] = useState<PointCluster[]>([]);
  const [choiceIds, setChoiceIds] = useState<string[]>([]);
  const choices = useMemo(() => globeChoices(points, choiceIds), [points, choiceIds]);
  const [ready, setReady] = useState(false);
  const [hover, setHover] = useState<{ point: GlobePoint; selection: string | null } | null>(null);
  const hovered = hover?.selection === selected ? hover.point : null;
  const [location, setLocation] = useState("Centered near Rehovot · location stays on this device");
  useEffect(() => { callbacks.current = { onSelect, onFailure, onViewportChange }; }, [onSelect, onFailure, onViewportChange]);
  const reducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  const locate = useCallback(() => {
    if (!navigator.geolocation) { setLocation("Location unavailable · you can still explore"); return; }
    setLocation("Waiting for location permission…");
    navigator.geolocation.getCurrentPosition(({ coords }) => {
      if (!mapRef.current) return;
      mapRef.current.flyTo({ center: [coords.longitude, coords.latitude], zoom: landingZoom(mapRef.current, coords.latitude), duration: reducedMotion() ? 0 : 1600 });
      setLocation("Centered near you · location stays on this device");
    }, () => { if (mapRef.current) setLocation("Location unavailable · you can still explore"); }, { timeout: 8000, maximumAge: 300000 });
  }, []);
  useEffect(() => {
    if (!container.current) return;
    let map: Map | undefined;
    let active = true;
    let loaded = false;
    const fail = () => { if (active) callbacks.current.onFailure(); };
    const timeout = window.setTimeout(() => { if (!loaded) fail(); }, 20000);
    try {
      map = new Map({ container: container.current, style: "https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json", center: FALLBACK_CENTER, zoom: 0.6, maxZoom: 12, canvasContextAttributes: { antialias: true }, attributionControl: { compact: true } });
      mapRef.current = map;
      map.addControl(new NavigationControl({ showCompass: false }), "bottom-right");
      map.addControl(new FullscreenControl({ container: container.current }), "top-right");
      map.on("moveend", () => { if (container.current && map) { container.current.dataset.projection = String(map.getProjection()?.type); container.current.dataset.zoom = String(map.getZoom()); } });
      map.on("webglcontextlost", fail);
      map.on("error", () => { if (!loaded) fail(); });
      map.once("load", () => {
        if (!active || !map) return;
        map.setProjection({ type: "globe" });
        const overlay = new MapLibreOverlay({ interleaved: false, layers: [], onError: fail });
        map.addControl(overlay);
        overlayRef.current = overlay;
        loaded = true;
        clearTimeout(timeout);
        setReady(true);
        map.flyTo({ center: FALLBACK_CENTER, zoom: landingZoom(map, FALLBACK_CENTER[1]), duration: reducedMotion() ? 0 : 1800 });
        // A prompt requires the explicit button; an already granted permission may be reused.
        navigator.permissions?.query({ name: "geolocation" }).then(permission => {
          if (active && permission.state === "granted") locate();
        }).catch(() => {});
      });
    } catch { fail(); }
    const resize = new ResizeObserver(() => {
      // Do not turn a transient hidden/collapsed panel into a permanent zoom-out.
      if (!map || !container.current?.clientWidth || !container.current.clientHeight) return;
      map.resize();
      const cap = landingZoom(map, map.getCenter().lat);
      if (map.getZoom() > cap) map.setZoom(cap);
    });
    resize.observe(container.current);
    return () => { active = false; clearTimeout(timeout); resize.disconnect(); overlayRef.current = null; mapRef.current = null; map?.remove(); };
  }, [locate]);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    let frame: number | null = null;
    const update = () => {
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        const canvas = map.getContainer();
        callbacks.current.onViewportChange(viewportPostingIds(points, canvas.clientWidth, canvas.clientHeight,
          point => map.project([point.lng, point.lat]), screen => map.unproject([screen.x, screen.y])));
      });
    };
    update();
    map.on("move", update);
    map.on("resize", update);
    return () => { if (frame !== null) cancelAnimationFrame(frame); map.off("move", update); map.off("resize", update); };
  }, [points, ready]);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const update = () => setClusters(clusterPoints(thinPoints(points, selected), point => {
      const screen = map.project([point.lng, point.lat]);
      const back = map.unproject(screen);
      const longitudeDelta = Math.abs(((back.lng - point.lng + 540) % 360) - 180);
      if (longitudeDelta > 0.01 || Math.abs(back.lat - point.lat) > 0.01) return null;
      return screen;
    }));
    const frame = requestAnimationFrame(update);
    map.on("moveend", update);
    map.on("resize", update);
    return () => { cancelAnimationFrame(frame); map.off("moveend", update); map.off("resize", update); };
  }, [points, selected, ready]);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map || !overlayRef.current) return;
    overlayRef.current.setProps({
      layers: [new ScatterplotLayer<PointCluster>({
        id: "posting-points", data: clusters, pickable: true,
        radiusUnits: "pixels", getRadius: cluster => cluster.members.length > 1 ? 15 : cluster.anchor.posting_id === selected || cluster.anchor.posting_id === hovered?.posting_id ? 11 : 6,
        getPosition: cluster => [cluster.anchor.lng, cluster.anchor.lat], getFillColor: cluster => scoreColor(clusterScore(cluster)),
        stroked: true, getLineColor: [255, 255, 255, 220], lineWidthUnits: "pixels", getLineWidth: cluster => cluster.members.some(point => point.posting_id === selected) ? 2 : 0.5,
        transitions: { getRadius: 160 }, updateTriggers: { getRadius: [selected, hovered?.posting_id], getLineWidth: [selected] },
        onHover: info => setHover(info.object?.members.length === 1 ? { point: info.object.anchor, selection: selected } : null),
        onClick: info => { if (info.object?.members.length === 1) callbacks.current.onSelect(info.object.anchor.posting_id); },
      })],
    });
    const markers = clusters.filter(cluster => cluster.members.length > 1).map(cluster => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "globe-cluster";
      button.setAttribute("aria-label", `${cluster.members.length} postings near ${cluster.anchor.job.location ?? "this location"}`);
      button.setAttribute("aria-controls", "globe-posting-choices");
      button.textContent = String(cluster.members.length);
      button.style.setProperty("--cluster-color", scoreCss(clusterScore(cluster)));
      button.onclick = () => {
        setHover(null);
        setChoiceIds(cluster.members.map(point => point.posting_id));
        map.flyTo({ center: [cluster.anchor.lng, cluster.anchor.lat], zoom: Math.min(map.getZoom() + 2, map.getMaxZoom()), duration: reducedMotion() ? 0 : 800 });
      };
      return new Marker({ element: button }).setLngLat([cluster.anchor.lng, cluster.anchor.lat]).addTo(map);
    });
    return () => { markers.forEach(marker => marker.remove()); };
  }, [clusters, selected, hovered, ready]);
  const selectedPoint = points.find(point => point.posting_id === selected);
  const selectedLat = selectedPoint?.lat, selectedLng = selectedPoint?.lng;
  useEffect(() => {
    if (ready && selectedLat !== undefined && selectedLng !== undefined && mapRef.current) {
      mapRef.current.flyTo({ center: [selectedLng, selectedLat], zoom: landingZoom(mapRef.current, selectedLat), duration: reducedMotion() ? 0 : 1200 });
    }
  }, [selected, ready, selectedLat, selectedLng]);
  const focused = hovered && points.some(point => point.posting_id === hovered.posting_id) ? hovered : selectedPoint;
  return <section className="job-globe-shell" aria-label="Posting locations globe">
    <div onPointerLeave={() => setHover(null)} className="job-globe">
      <div ref={container} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} />
      <p className="pointer-events-none absolute left-4 top-4 rounded-md bg-slate-950/80 px-2 py-1 text-xs text-slate-200">{ready ? "Drag to explore · select a posting" : "Preparing the globe…"}</p>
    </div>
    <div className="globe-footer">
      <div className="flex flex-wrap gap-4 text-xs">{scoreBands.map(band => <span key={band.label} className="flex items-center gap-1.5"><i aria-hidden="true" className="inline-block size-3 rounded-full" style={{backgroundColor:scoreCss(band.score)}} />{band.label}</span>)}</div>
      <p className="mt-2 text-xs text-muted-foreground">Counts group nearby postings · color shows the highest fit in the group.</p>
      {choices.length > 0 && <div className="mt-3 rounded-lg border p-2" id="globe-posting-choices" role="region" aria-live="polite" aria-label="Postings at this point"><p className="p-2 text-sm">Choose from {choices.length} postings</p><div className="max-h-40 overflow-y-auto">{choices.map(point => <button key={point.posting_id} type="button" aria-pressed={selected === point.posting_id} onClick={() => { setHover(null); callbacks.current.onSelect(point.posting_id); }} className="block min-h-11 w-full rounded-md px-2 py-3 text-left text-sm hover:bg-muted focus-visible:outline-2">{point.job.title} · {point.job.company}</button>)}</div><button type="button" onClick={() => setChoiceIds([])} className="min-h-11 px-2 text-sm underline">Close posting choices</button></div>}
      <div className="mt-3 flex flex-wrap items-center gap-3"><button type="button" onClick={locate} className="min-h-11 rounded-lg border px-3 py-2 text-sm focus-visible:outline-2">{location.startsWith("Location unavailable") ? "Retry location" : "Use my location"}</button><p role="status" className="text-xs">{location}</p></div>
      <div className="mt-3 min-h-24 rounded-lg border p-3" data-globe-posting={focused?.posting_id} data-globe-hover={hovered?.posting_id} aria-live="polite">
        {focused ? <><p className="text-xs">{focused.job.company} · {focused.job.score === null ? "Unscored" : `${focused.job.score} fit`}</p><p className="mt-1 font-medium">{focused.job.title}</p><p className="mt-1 text-xs">{pointLabel(focused)}</p><p className="mt-1 break-all text-xs">Source: {focused.source}</p></> : <p className="text-sm text-muted-foreground">Select a posting to see its location and source.</p>}
      </div>
    </div>
  </section>;
}
