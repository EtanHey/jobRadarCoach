"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState, useMemo } from "react";
import { Map, NavigationControl, FullscreenControl, Marker, setWorkerUrl, type IControl, type MapOptions } from "maplibre-gl";
import { MapLibreOverlay } from "@deck.gl/maplibre";
import { ScatterplotLayer } from "@deck.gl/layers";
import { FALLBACK_CENTER, pointLabel, scoreColor, scoreCss, thinPoints, clusterPoints, clusterScore, globeChoices, type PointCluster, type GlobePoint } from "@/lib/globe-model";
import { cameraNeedsReset, focusPointCamera, locationCameraBounds, usableMapSize, viewportPostingIds } from "@/lib/globe-viewport";
import { loadGlobeStyle } from "@/lib/globe-style";
import "maplibre-gl/dist/maplibre-gl.css";

setWorkerUrl(new URL("../lib/generated/maplibre-worker.mjs", import.meta.url).href);

function landingZoomForSize(width: number, height: number, latitude: number) {
  const edge = Math.min(width, height);
  // The first visible container supplies the landing size; later resizes retain the camera.
  if (edge <= 0) return 1.7;
  return Math.min(1.9, Math.log2(edge * Math.max(0.15, Math.cos(latitude * Math.PI / 180)) / 180) + 0.55);
}
function landingZoom(map: Map, latitude: number) {
  return landingZoomForSize(map.getContainer().clientWidth, map.getContainer().clientHeight, latitude);
}
function reducedMotion() { return window.matchMedia("(prefers-reduced-motion: reduce)").matches; }
function moveToLocation(map: Map, location: string, points: GlobePoint[], reset: boolean, duration: number) {
  const bounds = reset ? null : locationCameraBounds(location, points);
  const easing = (t: number) => 1 - (1 - t) ** 3;
  if (bounds) {
    const padded = bounds[0][0] === bounds[1][0] && bounds[0][1] === bounds[1][1]
      ? [[bounds[0][0] - .25, bounds[0][1] - .25], [bounds[1][0] + .25, bounds[1][1] + .25]] as typeof bounds : bounds;
    const camera = map.cameraForBounds(padded, { padding: 48, maxZoom: 10 });
    if (camera) map.easeTo({ ...camera, duration, easing });
  } else {
    const center: [number, number] = location === "other" && !reset && points.length
      ? [points.reduce((sum, point) => sum + point.lng, 0) / points.length, points.reduce((sum, point) => sum + point.lat, 0) / points.length]
      : FALLBACK_CENTER;
    map.easeTo({ center, zoom: landingZoom(map, FALLBACK_CENTER[1]), duration, easing });
  }
}
function makeLocationControl(locate: () => void): IControl {
  let root: HTMLDivElement | null = null;
  return {
    onAdd() {
      root = document.createElement("div");
      root.className = "maplibregl-ctrl maplibregl-ctrl-location-wrap";
      const group = document.createElement("div");
      group.className = "maplibregl-ctrl-group";
      const button = document.createElement("button");
      button.type = "button";
      button.className = "maplibregl-ctrl-location";
      button.setAttribute("aria-label", "Use my location");
      button.title = "Job Radar does not store your location. CARTO receives map tiles for the displayed area.";
      const icon = document.createElementNS("http://www.w3.org/2000/svg", "svg");
      icon.setAttribute("viewBox", "0 0 24 24");
      icon.setAttribute("width", "22");
      icon.setAttribute("height", "22");
      icon.setAttribute("fill", "none");
      icon.setAttribute("stroke", "currentColor");
      icon.setAttribute("stroke-width", "2.25");
      icon.setAttribute("stroke-linecap", "round");
      icon.setAttribute("aria-hidden", "true");
      icon.innerHTML = '<circle cx="12" cy="12" r="6.5"/><path d="M12 2v3.5M12 18.5V22M2 12h3.5M18.5 12H22"/>';
      button.append(icon);
      button.onclick = locate;
      const status = document.createElement("span");
      status.className = "maplibregl-ctrl-location-status";
      status.setAttribute("role", "status");
      status.setAttribute("aria-live", "polite");
      group.append(button);
      root.append(group, status);
      return root;
    },
    onRemove() { root?.remove(); root = null; },
  };
}

type Props = { active: boolean; dataReady: boolean; onViewportChange: (ids: string[]) => void; points: GlobePoint[]; selected: string | null; selectionRequest: number; selectionSource: "point" | "rail"; location: string; cameraAction: { kind: "location" | "reset"; id: number }; arrivalRequest: number; onCameraAwayChange: (away: boolean) => void; onSelect: (id: string) => void; onFailure: () => void };
export default function JobGlobe({ active, dataReady, points, selected, selectionRequest, selectionSource, location, cameraAction, arrivalRequest, onCameraAwayChange, onSelect, onFailure, onViewportChange }: Props) {
  const container = useRef<HTMLDivElement>(null);
  const activeRef = useRef(active);
  const cameraRef = useRef<{ center: [number, number]; zoom: number; bearing: number; pitch: number } | null>(null);
  const pendingFailureRef = useRef(false);
  const mapRef = useRef<Map | null>(null);
  const overlayRef = useRef<MapLibreOverlay | null>(null);
  const markerRegistry = useRef(new globalThis.Map<string, { marker: Marker; button: HTMLButtonElement; lng: number; lat: number }>());
  const initialFocusPending = useRef(true);
  const handledCameraAction = useRef(cameraAction.id);
  const cameraActionRef = useRef(cameraAction);
  const handledSelectionRequest = useRef(0);
  const dataReadyRef = useRef(dataReady);
  const startMapRef = useRef<() => void>(() => {});
  const callbacks = useRef({ onSelect, onFailure, onViewportChange, onCameraAwayChange });
  const [clusters, setClusters] = useState<PointCluster[]>([]);
  const [choiceIds, setChoiceIds] = useState<string[]>([]);
  const choices = useMemo(() => globeChoices(points, choiceIds), [points, choiceIds]);
  const [ready, setReady] = useState(false);
  const [showDragHint, setShowDragHint] = useState(() => {
    try { return localStorage.getItem("job-globe-dragged") !== "1"; }
    catch { return true; }
  });
  const arrivalPending = useRef(false);
  const arrivalSeen = useRef(0);
  const pulsedSelection = useRef<string | null>(null);
  const arrivalInProgress = useRef(false);
  const [hover, setHover] = useState<{ point: GlobePoint; selection: string | null } | null>(null);
  const [hiddenFocusedSelection, setHiddenFocusedSelection] = useState<{ selected: string | null; request: number } | null>(null);
  const locationStatusTimer = useRef<number | null>(null);
  const selectedRef = useRef(selected);
  const locationRef = useRef(location);
  const pointsRef = useRef(points);
  useLayoutEffect(() => {
    dataReadyRef.current = dataReady; locationRef.current = location; pointsRef.current = points; cameraActionRef.current = cameraAction;
    if (cameraAction.id !== handledCameraAction.current) cameraRef.current = null;
  }, [dataReady, location, points, cameraAction]);
  const selectionRequestRef = useRef(selectionRequest);
  const hovered = hover?.selection === selected ? hover.point : null;
  const canInteract = useCallback(() => {
    const element = container.current;
    const canvas = mapRef.current?.getCanvas();
    return activeRef.current && !!element && !!canvas && usableMapSize(element.clientWidth, element.clientHeight) && usableMapSize(canvas.clientWidth, canvas.clientHeight);
  }, []);
  useLayoutEffect(() => {
    activeRef.current = active;
    if (active && pendingFailureRef.current) { pendingFailureRef.current = false; callbacks.current.onFailure(); return; }
    const map = mapRef.current;
    if (!map) return;
    if (!active) {
      map.stop();
      const center = map.getCenter();
      cameraRef.current = { center: [center.lng, center.lat], zoom: map.getZoom(), bearing: map.getBearing(), pitch: map.getPitch() };
      return;
    }
    if (!container.current || !usableMapSize(container.current.clientWidth, container.current.clientHeight)) return;
    const savedCamera = cameraRef.current;
    const actionAtShow = cameraActionRef.current.id;
    const restoreSavedCamera = actionAtShow === handledCameraAction.current;
    if (!restoreSavedCamera) cameraRef.current = null;
    const restore = () => { map.resize(); if (savedCamera && restoreSavedCamera && cameraActionRef.current.id === actionAtShow) map.jumpTo(savedCamera); };
    restore();
    const frame = requestAnimationFrame(() => { restore(); if (cameraRef.current === savedCamera) cameraRef.current = null; });
    return () => cancelAnimationFrame(frame);
  }, [active]);
  useEffect(() => { callbacks.current = { onSelect: (id: string) => { setHiddenFocusedSelection(null); onSelect(id); }, onFailure, onViewportChange, onCameraAwayChange }; }, [onSelect, onFailure, onViewportChange, onCameraAwayChange]);
  useEffect(() => { selectionRequestRef.current = selectionRequest; }, [selectionRequest]);
  useEffect(() => { selectedRef.current = selected; }, [selected]);
  useEffect(() => { if (dataReady) startMapRef.current(); }, [dataReady]);
  useEffect(() => {
    function layout() { if (!container.current || !usableMapSize(container.current.clientWidth, container.current.clientHeight)) return; mapRef.current?.resize(); mapRef.current?.triggerRepaint(); }
    if (arrivalRequest > arrivalSeen.current) { arrivalSeen.current = arrivalRequest; arrivalPending.current = true; }
    function runArrival() {
      const map = mapRef.current;
      if (!map || !arrivalPending.current || !activeRef.current) return;
      arrivalPending.current = false;
      if (locationRef.current !== "other" || cameraActionRef.current.id !== 0) return;
      const zoom = map.getZoom();
      arrivalInProgress.current = true;
      map.jumpTo({ zoom: zoom - .6 });
      map.easeTo({ zoom, duration: 600, easing: t => 1 - (1 - t) ** 3 });
      map.once("moveend", () => {
        const cap = landingZoom(map, FALLBACK_CENTER[1]);
        if (map.getZoom() > cap) map.jumpTo({ zoom: cap });
        arrivalInProgress.current = false;
      });
    }
    window.addEventListener("job-globe-layout", layout);
    if (ready) runArrival();
    return () => { window.removeEventListener("job-globe-layout", layout); };
  }, [ready, arrivalRequest]);
  useEffect(() => {
    if (!active || ready) return;
    const timeout = window.setTimeout(() => callbacks.current.onFailure(), 20000);
    return () => clearTimeout(timeout);
  }, [active, ready]);
  const locate = useCallback(() => {
    const map = mapRef.current;
    const status = map?.getContainer().querySelector<HTMLElement>(".maplibregl-ctrl-location-status");
    const button = map?.getContainer().querySelector<HTMLButtonElement>(".maplibregl-ctrl-location");
    const announce = (message: string, clearAfterMs?: number) => {
      if (!status) return;
      if (locationStatusTimer.current !== null) window.clearTimeout(locationStatusTimer.current);
      status.textContent = message;
      locationStatusTimer.current = clearAfterMs === undefined ? null : window.setTimeout(() => {
        if (status.isConnected && status.textContent === message) status.textContent = "";
        locationStatusTimer.current = null;
      }, clearAfterMs);
    };
    if (!navigator.geolocation) {
      announce("Location unavailable · you can still explore", 12000);
      if (button) button.setAttribute("aria-label", "Retry location");
      return;
    }
    announce("Waiting for location permission…");
    navigator.geolocation.getCurrentPosition(({ coords }) => {
      if (!map) return;
      map.flyTo({ center: [coords.longitude, coords.latitude], zoom: Math.min(map.getMaxZoom(), Math.max(map.getZoom(), 10)), duration: reducedMotion() ? 0 : 1600 });
      setHover(null);
      setHiddenFocusedSelection({ selected: selectedRef.current, request: selectionRequestRef.current });
      announce("Centered near you · not saved by Job Radar", 4500);
      if (button) button.setAttribute("aria-label", "Use my location");
    }, () => {
      if (map) announce("Location unavailable · you can still explore", 12000);
      if (button) button.setAttribute("aria-label", "Retry location");
    }, { timeout: 8000, maximumAge: 300000 });
  }, []);
  useEffect(() => {
    if (!container.current) return;
    let map: Map | undefined;
    let mounted = true;
    let loaded = false;
    let initialZoom = 0;
    let cameraStarts = 0;
    const registry = markerRegistry.current;
    let style: MapOptions["style"];
    const fail = () => {
      if (!mounted) return;
      if (!activeRef.current) { pendingFailureRef.current = true; return; }
      callbacks.current.onFailure();
    };
    const startMap = () => {
      if (!mounted || map || !style || !activeRef.current || !container.current || !usableMapSize(container.current.clientWidth, container.current.clientHeight)) return;
      if (locationRef.current === "other" && !dataReadyRef.current) return;
      try {
        initialZoom = landingZoomForSize(container.current.clientWidth, container.current.clientHeight, FALLBACK_CENTER[1]);
        map = new Map({ container: container.current, style, center: FALLBACK_CENTER, zoom: initialZoom, maxZoom: 12, trackResize: false, canvasContextAttributes: { antialias: true }, attributionControl: { compact: true } });
        mapRef.current = map;
        map.getCanvas().tabIndex = 0;
        map.on("dragstart", () => { setShowDragHint(false); try { localStorage.setItem("job-globe-dragged", "1"); } catch { /* Storage can be unavailable. */ } });
        map.addControl(new NavigationControl({ showCompass: false }), "bottom-right");
        map.addControl(new FullscreenControl({ container: container.current }), "top-right");
        map.addControl(makeLocationControl(locate), "top-right");
        const publishCamera = () => { if (container.current && map) {
          container.current.dataset.projection = String(map.getProjection()?.type);
          container.current.dataset.zoom = String(map.getZoom());
          container.current.dataset.center = `${map.getCenter().lng},${map.getCenter().lat}`;
          container.current.dataset.bearing = String(map.getBearing());
          container.current.dataset.pitch = String(map.getPitch());
          if (process.env.NODE_ENV !== "production") {
            const bounds = locationCameraBounds(locationRef.current, pointsRef.current);
            if (bounds) container.current.dataset.locationCorners = JSON.stringify([
              [bounds[0][0], bounds[0][1]], [bounds[0][0], bounds[1][1]],
              [bounds[1][0], bounds[0][1]], [bounds[1][0], bounds[1][1]],
            ].map(([lng, lat]) => { const screen = map!.project([lng, lat]); return [screen.x, screen.y]; }));
            else delete container.current.dataset.locationCorners;
          }
        } };
        map.on("moveend", publishCamera);
        if (process.env.NODE_ENV !== "production") map.on("movestart", () => { if (container.current) container.current.dataset.cameraStarts = String(++cameraStarts); });
        map.on("moveend", () => {
          if (!map) return;
          if (arrivalInProgress.current) return;
          const center = map.getCenter();
          callbacks.current.onCameraAwayChange(cameraNeedsReset([center.lng, center.lat], map.getZoom(), FALLBACK_CENTER, landingZoom(map, FALLBACK_CENTER[1])));
        });
        map.on("webglcontextlost", fail);
        map.on("error", event => { if (!loaded) { console.error("Globe initialization error", event.error); fail(); } });
        map.once("load", () => {
          if (!mounted || !map) return;
          if (locationRef.current && (locationRef.current !== "other" || dataReadyRef.current)) {
            moveToLocation(map, locationRef.current, pointsRef.current, false, 0);
            initialFocusPending.current = false;
            handledCameraAction.current = cameraActionRef.current.id;
          }
          publishCamera();
          const overlay = new MapLibreOverlay({ interleaved: false, layers: [], onError: fail });
          map.addControl(overlay);
          overlayRef.current = overlay;
          overlay.setProps({ getCursor: ({ isDragging, isHovering }) => isDragging ? "grabbing" : isHovering ? "pointer" : "grab" });
          loaded = true;
          setReady(true);
        });
      } catch (error) { console.error("Globe construction error", error); fail(); }
    };
    const resize = new ResizeObserver(() => {
      if (!container.current || !usableMapSize(container.current.clientWidth, container.current.clientHeight)) return;
      if (map) {
        map.resize();
        if (activeRef.current && cameraRef.current) { map.jumpTo(cameraRef.current); cameraRef.current = null; }
      } else if (pendingFailureRef.current && activeRef.current) fail();
      else startMap();
    });
    resize.observe(container.current);
    startMapRef.current = startMap;
    loadGlobeStyle()
      .then(result => { if (mounted) { style = result; startMap(); } })
      .catch(error => { if (mounted) { console.error("Globe style error", error); fail(); } });
    return () => { mounted = false; startMapRef.current = () => {}; pendingFailureRef.current = false; resize.disconnect(); overlayRef.current = null; mapRef.current = null; registry.clear(); map?.remove(); if (locationStatusTimer.current !== null) { window.clearTimeout(locationStatusTimer.current); locationStatusTimer.current = null; } };
  }, [locate]);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    let frame: number | null = null;
    const update = () => {
      if (frame !== null) return;
      frame = requestAnimationFrame(() => {
        frame = null;
        if (map.isMoving() || map.getProjection()?.type !== "globe") {
          map.off("idle", update);
          map.once("idle", update);
          return;
        }
        const canvas = map.getContainer();
        if (!canvas.clientWidth || !canvas.clientHeight) return;
        callbacks.current.onViewportChange(viewportPostingIds(points, canvas.clientWidth, canvas.clientHeight,
          point => map.project([point.lng, point.lat]), screen => map.unproject([screen.x, screen.y])));
      });
    };
    update();
    map.on("moveend", update);
    map.on("resize", update);
    return () => { if (frame !== null) cancelAnimationFrame(frame); map.off("moveend", update); map.off("resize", update); map.off("idle", update); };
  }, [points, ready]);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !map) return;
    const update = () => {
      if (!canInteract()) return;
      setClusters(clusterPoints(thinPoints(points, selected), point => {
        try {
          const screen = map.project([point.lng, point.lat]);
          if (!Number.isFinite(screen.x) || !Number.isFinite(screen.y)) return null;
          const back = map.unproject(screen);
          if (!Number.isFinite(back.lng) || !Number.isFinite(back.lat)) return null;
          const longitudeDelta = Math.abs(((back.lng - point.lng + 540) % 360) - 180);
          if (longitudeDelta > 0.01 || Math.abs(back.lat - point.lat) > 0.01) return null;
          return screen;
        } catch (error) {
          if (!(error instanceof Error) || !error.message.includes("Invalid LngLat")) throw error;
          return null;
        }
      }));
    };
    const frame = requestAnimationFrame(update);
    map.on("moveend", update);
    map.on("resize", update);
    return () => { cancelAnimationFrame(frame); map.off("moveend", update); map.off("resize", update); };
  }, [points, selected, ready, canInteract]);
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
        onHover: info => { if (canInteract()) { if (info.object?.members.length === 1) setHiddenFocusedSelection(null); setHover(info.object?.members.length === 1 ? { point: info.object.anchor, selection: selected } : null); } },
        onClick: info => { if (canInteract() && info.object?.members.length === 1) callbacks.current.onSelect(info.object.anchor.posting_id); },
      })],
    });
    if (!selected) pulsedSelection.current = null;
    const pulseSelection = selected !== null && selected !== pulsedSelection.current;
    const next = new Set<string>();
    for (const cluster of clusters.filter(cluster => cluster.members.length > 1)) {
      const key = cluster.members.map(point => point.posting_id).sort().join("|");
      next.add(key);
      let entry = markerRegistry.current.get(key);
      if (!entry) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "globe-cluster";
        button.setAttribute("aria-controls", "globe-posting-choices");
        const marker = new Marker({ element: button }).setLngLat([cluster.anchor.lng, cluster.anchor.lat]).addTo(map);
        entry = { marker, button, lng: cluster.anchor.lng, lat: cluster.anchor.lat };
        markerRegistry.current.set(key, entry);
      }
      const { button } = entry;
      if (pulseSelection) {
        const selectedHere = cluster.members.some(point => point.posting_id === selected);
        button.classList.toggle("globe-cluster-selected", selectedHere);
        if (selectedHere) pulsedSelection.current = selected;
      } else if (!selected) button.classList.remove("globe-cluster-selected");
      button.setAttribute("aria-label", `${cluster.members.length} postings near ${cluster.anchor.job.location ?? "this location"}`);
      button.textContent = String(cluster.members.length);
      button.style.setProperty("--cluster-color", scoreCss(clusterScore(cluster)));
      if (entry.lng !== cluster.anchor.lng || entry.lat !== cluster.anchor.lat) {
        entry.marker.setLngLat([cluster.anchor.lng, cluster.anchor.lat]);
        entry.lng = cluster.anchor.lng; entry.lat = cluster.anchor.lat;
      }
      button.onclick = () => {
        if (!canInteract()) return;
        setHover(null);
        setChoiceIds(cluster.members.map(point => point.posting_id));
        map.flyTo({ center: [cluster.anchor.lng, cluster.anchor.lat], zoom: Math.min(map.getZoom() + 2, map.getMaxZoom()), duration: reducedMotion() ? 0 : 800 });
      };
    }
    for (const [key, entry] of markerRegistry.current) if (!next.has(key)) { entry.marker.remove(); markerRegistry.current.delete(key); }
  }, [clusters, selected, hovered, ready, canInteract]);
  const selectedPoint = points.find(point => point.posting_id === selected);
  const selectedLat = selectedPoint?.lat, selectedLng = selectedPoint?.lng;
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !active || !map || selectedLat === undefined || selectedLng === undefined || selectionRequest === 0 || selectionRequest === handledSelectionRequest.current) return;
    handledSelectionRequest.current = selectionRequest;
    const mapRect = map.getContainer().getBoundingClientRect();
    const drawerRect = selectionSource === "point" ? document.querySelector<HTMLElement>('[role="dialog"]')?.getBoundingClientRect() : undefined;
    // Base UI mounts the drawer portal after this effect on a direct point click.
    const drawerWidth = selectionSource === "point" ? drawerRect?.width ?? Math.min(innerWidth, 42 * parseFloat(getComputedStyle(document.documentElement).fontSize)) : 0;
    const overlap = Math.min(mapRect.width, Math.max(0, drawerWidth - (innerWidth - mapRect.right)));
    const coveredRight = overlap >= mapRect.width - 1 ? 0 : overlap;
    const screen = map.project([selectedLng, selectedLat]);
    const target = focusPointCamera({ zoom: map.getZoom(), width: mapRect.width, height: mapRect.height, coveredRight, x: screen.x, y: screen.y });
    if (process.env.NODE_ENV !== "production") map.getContainer().dataset.focusDecision = JSON.stringify({ selectionSource, coveredRight, x: screen.x, y: screen.y, target });
    if (target) map.easeTo({ center: [selectedLng, selectedLat], zoom: target.zoom, offset: [target.offsetX, 0], duration: reducedMotion() ? 0 : 600, easing: t => 1 - (1 - t) ** 3 });
  }, [selectionRequest, selectionSource, ready, active, selectedLat, selectedLng]);
  useEffect(() => {
    const map = mapRef.current;
    if (!ready || !active || !map) return;
    const initial = initialFocusPending.current;
    const explicit = cameraAction.id !== handledCameraAction.current;
    if (!initial && !explicit) return;
    if (location === "other" && points.length === 0 && !dataReady && !(explicit && cameraAction.kind === "reset")) return;
    initialFocusPending.current = false;
    handledCameraAction.current = cameraAction.id;
    if (initial && location === "" && !explicit) return;
    const resetting = explicit && cameraAction.kind === "reset";
    const duration = initial || reducedMotion() ? 0 : 900;
    moveToLocation(map, location, points, resetting, duration);
  }, [active, ready, dataReady, location, points, cameraAction]);
  const focused = hovered && points.some(point => point.posting_id === hovered.posting_id) ? hovered : selectedPoint;
  return <section className="job-globe-shell" aria-label="Posting locations globe">
    <div onPointerLeave={() => setHover(null)} className="job-globe">
      <div ref={container} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} />
      {!ready && <p className="pointer-events-none absolute left-4 top-4 rounded-md bg-slate-950/80 px-2 py-1 text-xs text-slate-200">Preparing the globe…</p>}
      {ready && showDragHint && <p className="pointer-events-none absolute left-4 top-4 rounded-md bg-slate-950/80 px-2 py-1 text-xs text-slate-200">Drag to spin · scroll to zoom</p>}
      {choices.length > 0 && <div className="absolute left-3 top-32 z-10 max-h-[calc(100%-11rem)] w-64 max-w-[calc(100%-1.5rem)] overflow-y-auto rounded-xl border bg-card p-2 shadow-lg" id="globe-posting-choices" role="region" aria-live="polite" aria-label="Postings at this point"><p className="p-2 text-sm">Choose from {choices.length} postings</p><div className="max-h-40 overflow-y-auto">{choices.map(point => <button key={point.posting_id} type="button" aria-pressed={selected === point.posting_id} onClick={() => { setHover(null); callbacks.current.onSelect(point.posting_id); }} className="block min-h-11 w-full rounded-md px-2 py-3 text-left text-sm hover:bg-muted focus-visible:outline-2">{point.job.title} · {point.job.company}</button>)}</div><button type="button" onClick={() => setChoiceIds([])} className="min-h-11 px-2 text-sm underline">Close posting choices</button></div>}
      {focused && choices.length === 0 && !(hiddenFocusedSelection?.selected === selected && hiddenFocusedSelection.request === selectionRequest) && <div className="absolute bottom-16 left-3 z-10 max-w-64 rounded-xl border bg-card/95 p-3 text-xs shadow-lg" data-globe-posting={focused.posting_id} data-globe-hover={hovered?.posting_id} aria-live="polite"><p>{focused.job.company} · {focused.job.score === null ? "Unscored" : `${focused.job.score} fit`}</p><p className="mt-1 font-medium">{focused.job.title}</p><p className="mt-1">{pointLabel(focused)}</p><p className="mt-1 break-all">Source: {focused.source}</p></div>}
    </div>
  </section>;
}
