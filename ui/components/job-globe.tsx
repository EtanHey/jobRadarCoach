"use client";

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { Map, LngLat, Marker, setWorkerUrl, type MapOptions } from "maplibre-gl";
import { Plus, Minus, LocateFixed, Maximize2, Minimize2 } from "lucide-react";
import { MapLibreOverlay } from "@deck.gl/maplibre";
import { ScatterplotLayer } from "@deck.gl/layers";
import { FALLBACK_CENTER, pointLabel, scoreColor, scoreCss, thinPoints, clusterPoints, clusterScore, clusterRoleIds, clusterIsStack, clusterPlace, type PointCluster, type GlobePoint } from "@/lib/globe-model";
import { cameraNeedsReset, focusPointCamera, locationCameraBounds, locationFlight, usableMapSize, viewportPostingIds } from "@/lib/globe-viewport";
import { activeGlobeTheme, applyGlobePaint, loadGlobeStyle } from "@/lib/globe-style";
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
function moveToLocation(map: Map, location: string, points: GlobePoint[], reset: boolean, animate: boolean) {
  const bounds = reset ? null : locationCameraBounds(location, points);
  let center: [number, number] = location === "other" && !reset && points.length
    ? [points.reduce((sum, point) => sum + point.lng, 0) / points.length, points.reduce((sum, point) => sum + point.lat, 0) / points.length]
    : FALLBACK_CENTER;
  let zoom = landingZoom(map, FALLBACK_CENTER[1]);
  if (bounds) {
    const padded = bounds[0][0] === bounds[1][0] && bounds[0][1] === bounds[1][1]
      ? [[bounds[0][0] - .25, bounds[0][1] - .25], [bounds[1][0] + .25, bounds[1][1] + .25]] as typeof bounds : bounds;
    const camera = map.cameraForBounds(padded, { padding: 48, maxZoom: 10 });
    if (!camera?.center || camera.zoom === undefined) return;
    const target = LngLat.convert(camera.center);
    center = [target.lng, target.lat]; zoom = camera.zoom;
  }
  if (!animate) { map.jumpTo({ center, zoom }); return; }
  const from = map.getCenter();
  map.flyTo({ center, zoom, ...locationFlight([from.lng, from.lat], map.getZoom(), center, zoom) });
}
type Props = { active: boolean; dataReady: boolean; onViewportChange: (ids: string[]) => void; points: GlobePoint[]; selected: string | null; selectionRequest: number; selectionSource: "point" | "rail"; location: string; cameraAction: { kind: "location" | "reset"; id: number }; arrivalRequest: number; onCameraAwayChange: (away: boolean) => void; onSelect: (id: string) => void; onBubble: (ids: string[], place: string) => void; bubbleIds: readonly string[]; onClearBubble: () => void; onFailure: () => void };
export default function JobGlobe({ active, dataReady, points, selected, selectionRequest, selectionSource, location, cameraAction, arrivalRequest, onCameraAwayChange, onSelect, onBubble, bubbleIds, onClearBubble, onFailure, onViewportChange }: Props) {
  const globeRoot = useRef<HTMLDivElement>(null);
  const container = useRef<HTMLDivElement>(null);
  const activeRef = useRef(active);
  const cameraRef = useRef<{ center: [number, number]; zoom: number; bearing: number; pitch: number } | null>(null);
  const pendingFailureRef = useRef(false);
  const mapRef = useRef<Map | null>(null);
  const overlayRef = useRef<MapLibreOverlay | null>(null);
  const markerRegistry = useRef(new globalThis.Map<string, { marker: Marker; button: HTMLButtonElement; lng: number; lat: number; ids: string[] }>());
  // D14 hover lives in refs and the DOM: pointer moves never commit React state or rebuild markers.
  const hoverIdRef = useRef<string | null>(null);
  const pointerHoverRef = useRef<string | null>(null);
  const renderLayersRef = useRef(() => {});
  const initialFocusPending = useRef(true);
  const handledCameraAction = useRef(cameraAction.id);
  const cameraActionRef = useRef(cameraAction);
  const handledSelectionRequest = useRef(0);
  const dataReadyRef = useRef(dataReady);
  const startMapRef = useRef<() => void>(() => {});
  const callbacks = useRef({ onSelect, onFailure, onViewportChange, onCameraAwayChange, onBubble, onClearBubble });
  const [clusters, setClusters] = useState<PointCluster[]>([]);
  const [hoveredBubble, setHoveredBubble] = useState<{ count: number; place: string } | null>(null);
  const [ready, setReady] = useState(false);
  const [zoomBounds, setZoomBounds] = useState({ atMin: false, atMax: false });
  const [darkMap, setDarkMap] = useState(false);
  const [fullscreen, setFullscreen] = useState(false);
  const [fullscreenAvailable, setFullscreenAvailable] = useState(false);
  const [locationLabel, setLocationLabel] = useState("Use my location");
  const [showDragHint, setShowDragHint] = useState(() => {
    try { return localStorage.getItem("job-globe-dragged") !== "1"; }
    catch { return true; }
  });
  const arrivalPending = useRef(false);
  const arrivalSeen = useRef(0);
  const pulsedSelection = useRef<string | null>(null);
  const arrivalInProgress = useRef(false);
  const featureClickAt = useRef(0);
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
  const setGlobeHover = useCallback((rowId: string | null) => {
    const previous = hoverIdRef.current;
    if (previous === rowId) return;
    hoverIdRef.current = rowId;
    if (process.env.NODE_ENV !== "production" && container.current) { if (rowId) container.current.dataset.hoverId = rowId; else delete container.current.dataset.hoverId; }
    if (previous) document.querySelector(`[data-globe-card="${previous}"]`)?.removeAttribute("data-hovered");
    if (rowId) document.querySelector(`[data-globe-card="${rowId}"]`)?.setAttribute("data-hovered", "");
    for (const { button, ids } of markerRegistry.current.values()) button.classList.toggle("globe-cluster-hovered", rowId !== null && ids.includes(rowId));
    renderLayersRef.current();
  }, []);
  const hoverPoint = useCallback((cluster: PointCluster | null) => {
    const point = cluster && clusterRoleIds(cluster.members).length === 1 ? cluster.anchor : null;
    if ((point?.posting_id ?? null) === pointerHoverRef.current) return;
    pointerHoverRef.current = point?.posting_id ?? null;
    setGlobeHover(point?.rowId ?? null);
    if (point) setHiddenFocusedSelection(null);
    setHover(point ? { point, selection: selectedRef.current } : null);
  }, [setGlobeHover]);
  useEffect(() => {
    const cardHover = (event: Event) => setGlobeHover((event as CustomEvent<string | null>).detail);
    window.addEventListener("job-globe-hover", cardHover);
    return () => window.removeEventListener("job-globe-hover", cardHover);
  }, [setGlobeHover]);
  useEffect(() => { if (process.env.NODE_ENV !== "production" && container.current) { if (selected) container.current.dataset.selectedId = selected; else delete container.current.dataset.selectedId; } }, [selected]);
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
  useEffect(() => { callbacks.current = { onSelect: (id: string) => { setHiddenFocusedSelection(null); onSelect(id); }, onFailure, onViewportChange, onCameraAwayChange, onBubble, onClearBubble }; }, [onSelect, onFailure, onViewportChange, onCameraAwayChange, onBubble, onClearBubble]);
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
      if (locationRef.current !== "" || cameraActionRef.current.id !== 0) return;
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
    if (!active || !dataReady || ready) return;
    const timeout = window.setTimeout(() => callbacks.current.onFailure(), 20000);
    return () => clearTimeout(timeout);
  }, [active, dataReady, ready]);
  const locate = useCallback(() => {
    const map = mapRef.current;
    const status = globeRoot.current?.querySelector<HTMLElement>(".maplibregl-ctrl-location-status");
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
      setLocationLabel("Retry location");
      return;
    }
    announce("Waiting for location permission…");
    navigator.geolocation.getCurrentPosition(({ coords }) => {
      if (!map) return;
      map.flyTo({ center: [coords.longitude, coords.latitude], zoom: Math.min(map.getMaxZoom(), Math.max(map.getZoom(), 10)), duration: reducedMotion() ? 0 : 1600 });
      pointerHoverRef.current = null;
      setHover(null);
      setHiddenFocusedSelection({ selected: selectedRef.current, request: selectionRequestRef.current });
      announce("Centered near you · not saved by Job Radar", 4500);
      setLocationLabel("Use my location");
    }, () => {
      if (map) announce("Location unavailable · you can still explore", 12000);
      setLocationLabel("Retry location");
    }, { timeout: 8000, maximumAge: 300000 });
  }, []);
  useEffect(() => {
    if (!container.current) return;
    let map: Map | undefined;
    let mounted = true;
    let loaded = false;
    let initialZoom = 0;
    let cameraStarts = 0;
    let theme = activeGlobeTheme();
    let themeRequest = 0;
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
        map.on("movestart", event => { if (event.originalEvent) callbacks.current.onClearBubble(); });
        map.on("click", event => {
          if ((event.originalEvent.target as Element)?.closest?.(".globe-cluster")) return;
          if (overlayRef.current?.pickObject({ x: event.point.x, y: event.point.y })?.object) return;
          const { clientX, clientY } = event.originalEvent;
          const bubble = [...registry.values()].find(({ button }) => {
            const rect = button.getBoundingClientRect();
            return clientX >= rect.left && clientX <= rect.right && clientY >= rect.top && clientY <= rect.bottom;
          });
          if (bubble) bubble.button.click();
          else window.setTimeout(() => { if (mounted && performance.now() - featureClickAt.current > 150) callbacks.current.onClearBubble(); }, 0);
        });
        map.on("dragstart", () => { setShowDragHint(false); try { localStorage.setItem("job-globe-dragged", "1"); } catch { /* Storage can be unavailable. */ } });
        map.on("style.load", () => {
          if (!map) return;
          applyGlobePaint(map);
          setDarkMap(theme === "dark");
          if (process.env.NODE_ENV !== "production" && container.current) {
            container.current.dataset.styleTheme = theme;
            container.current.dataset.waterColor = String(map.getPaintProperty("water", "fill-color"));
            container.current.dataset.landColor = String(map.getPaintProperty("background", "background-color"));
            container.current.dataset.borderColor = String(map.getPaintProperty("boundary_country_outline", "line-color"));
            container.current.dataset.labelColor = String(map.getPaintProperty("place_city_r6", "text-color"));
            container.current.dataset.skyColor = String(map.getSky()["sky-color"]);
          }
        });
        const updateZoomBounds = () => {
          if (!map) return;
          const atMin = map.getZoom() <= map.getMinZoom();
          const atMax = map.getZoom() >= map.getMaxZoom();
          setZoomBounds(current => current.atMin === atMin && current.atMax === atMax ? current : { atMin, atMax });
        };
        map.on("zoomend", updateZoomBounds);
        updateZoomBounds();
        const publishCamera = () => { if (process.env.NODE_ENV !== "production" && container.current && map) {
          const cameraMap = map;
          container.current.dataset.projection = String(map.getProjection()?.type);
          container.current.dataset.zoom = String(map.getZoom());
          container.current.dataset.center = `${map.getCenter().lng},${map.getCenter().lat}`;
          container.current.dataset.bearing = String(map.getBearing());
          container.current.dataset.pitch = String(map.getPitch());
          const bounds = locationCameraBounds(locationRef.current, pointsRef.current);
          if (bounds) container.current.dataset.locationCorners = JSON.stringify([
            [bounds[0][0], bounds[0][1]], [bounds[0][0], bounds[1][1]],
            [bounds[1][0], bounds[0][1]], [bounds[1][0], bounds[1][1]],
          ].map(([lng, lat]) => { const screen = cameraMap.project([lng, lat]); return [screen.x, screen.y]; }));
          else delete container.current.dataset.locationCorners;
        } };
        if (process.env.NODE_ENV !== "production") map.on("moveend", publishCamera);
        if (process.env.NODE_ENV !== "production") {
          const debugMap = map;
          let flightMinZoom = 0;
          map.on("movestart", () => { flightMinZoom = debugMap.getZoom(); if (container.current) container.current.dataset.cameraStarts = String(++cameraStarts); });
          map.on("move", () => { flightMinZoom = Math.min(flightMinZoom, debugMap.getZoom()); });
          map.on("moveend", () => { if (container.current) container.current.dataset.flightMinZoom = String(flightMinZoom); });
        }
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
            moveToLocation(map, locationRef.current, pointsRef.current, false, false);
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
    const updateTheme = () => {
      const next = activeGlobeTheme();
      if (next === theme && (style || themeRequest)) return;
      theme = next;
      const request = ++themeRequest;
      void loadGlobeStyle(next).then(result => {
        if (!mounted || request !== themeRequest) return;
        style = result;
        if (map && result) map.setStyle(result, { diff: true });
        else startMap();
      }).catch(error => { if (mounted && request === themeRequest) { console.error("Globe style error", error); fail(); } });
    };
    updateTheme();
    const themeObserver = new MutationObserver(updateTheme);
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["class"] });
    return () => { mounted = false; themeObserver.disconnect(); startMapRef.current = () => {}; pendingFailureRef.current = false; resize.disconnect(); overlayRef.current = null; mapRef.current = null; registry.clear(); map?.remove(); if (locationStatusTimer.current !== null) { window.clearTimeout(locationStatusTimer.current); locationStatusTimer.current = null; } };
  }, []);
  useEffect(() => {
    const changed = () => setFullscreen(document.fullscreenElement === globeRoot.current);
    setFullscreenAvailable(Boolean(document.fullscreenEnabled && globeRoot.current?.requestFullscreen && document.exitFullscreen));
    document.addEventListener("fullscreenchange", changed);
    return () => document.removeEventListener("fullscreenchange", changed);
  }, []);
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
    const hoverId = () => hoverIdRef.current;
    const ringed = (cluster: PointCluster) => { const ids = clusterRoleIds(cluster.members); return ids.includes(selected ?? "") || ids.length === 1 && ids[0] === hoverId(); };
    const radius = (cluster: PointCluster) => {
      if (clusterRoleIds(cluster.members).length > 1) return 15;
      if (clusterRoleIds(cluster.members).includes(selected ?? "")) return 11;
      if (ringed(cluster)) return 10;
      const score = clusterScore(cluster);
      return score === null || score >= 60 && score < 80 ? 6 : score >= 80 ? 7 : 5;
    };
    const tokenColor = (name: string): [number, number, number, number] => {
      const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
      const canvas = document.createElement("canvas");
      canvas.width = canvas.height = 1;
      const context = canvas.getContext("2d");
      if (!context) throw new Error("Globe colour canvas unavailable");
      context.fillStyle = value;
      context.fillRect(0, 0, 1, 1);
      return [...context.getImageData(0, 0, 1, 1).data] as [number, number, number, number];
    };
    const paper = tokenColor("--globe-paper");
    const selectedRing = tokenColor("--globe-select");
    const unscoredRing = tokenColor("--globe-unscored-ring");
    const activateCluster = (cluster: PointCluster) => {
      if (!canInteract()) return;
      featureClickAt.current = performance.now();
      pointerHoverRef.current = null;
      setHover(null);
      setHoveredBubble(null);
      const ids = clusterRoleIds(cluster.members);
      callbacks.current.onBubble(ids, clusterPlace(cluster.members));
      const stack = clusterIsStack(cluster.members);
      const lng = cluster.members.map(point => point.lng), lat = cluster.members.map(point => point.lat);
      const camera = stack ? null : map.cameraForBounds([[Math.min(...lng), Math.min(...lat)], [Math.max(...lng), Math.max(...lat)]], { padding: 64 });
      map.easeTo({ center: stack ? [cluster.anchor.lng, cluster.anchor.lat] : camera?.center ?? [cluster.anchor.lng, cluster.anchor.lat], zoom: stack ? Math.min(map.getMaxZoom(), Math.max(map.getZoom(), 8)) : Math.min(map.getMaxZoom(), Math.max(map.getZoom() + 1, camera?.zoom ?? 0)), duration: reducedMotion() ? 0 : 700, easing: t => 1 - (1 - t) ** 3 });
    };
    const renderLayers = () => overlayRef.current?.setProps({
      layers: [...(!darkMap ? [new ScatterplotLayer<PointCluster>({
        id: "posting-hairlines", data: clusters, pickable: false, filled: false, stroked: true,
        radiusUnits: "pixels", getRadius: cluster => radius(cluster) + 2.5,
        getPosition: cluster => [cluster.anchor.lng, cluster.anchor.lat], getLineColor: [8, 17, 28, 153],
        lineWidthUnits: "pixels", getLineWidth: 1, updateTriggers: { getRadius: [selected, hoverId()] },
      })] : []), new ScatterplotLayer<PointCluster>({
        id: "posting-sticker-rings", data: clusters, pickable: false,
        radiusUnits: "pixels", getRadius: cluster => radius(cluster) + 1,
        getPosition: cluster => [cluster.anchor.lng, cluster.anchor.lat], filled: false, stroked: true,
        getLineColor: paper, lineWidthUnits: "pixels", getLineWidth: 2,
        updateTriggers: { getRadius: [selected, hoverId()] },
      }), new ScatterplotLayer<PointCluster>({
        id: "posting-points", data: clusters, pickable: true,
        radiusUnits: "pixels", getRadius: radius,
        getPosition: cluster => [cluster.anchor.lng, cluster.anchor.lat], getFillColor: cluster => clusterScore(cluster) === null ? [0, 0, 0, 0] : scoreColor(clusterScore(cluster)),
        stroked: true, getLineColor: cluster => ringed(cluster) ? selectedRing : clusterScore(cluster) === null ? unscoredRing : [0, 0, 0, 0], lineWidthUnits: "pixels", getLineWidth: cluster => clusterScore(cluster) === null || ringed(cluster) ? 2 : 0,
        transitions: { getRadius: 160 }, updateTriggers: { getRadius: [selected, hoverId()], getLineWidth: [selected, hoverId()], getLineColor: [selected, darkMap, hoverId()] },
        onHover: info => { if (canInteract()) hoverPoint(info.object ?? null); },
        onClick: info => { if (canInteract() && info.object) { featureClickAt.current = performance.now(); if (clusterRoleIds(info.object.members).length === 1) callbacks.current.onSelect(info.object.anchor.posting_id); else activateCluster(info.object); } },
      })],
    });
    renderLayers();
    renderLayersRef.current = renderLayers;
    if (process.env.NODE_ENV !== "production" && container.current) container.current.dataset.dotRingColor = paper.join(",");
    if (!selected) pulsedSelection.current = null;
    const pulseSelection = selected !== null && selected !== pulsedSelection.current;
    const next = new Set<string>();
    for (const cluster of clusters.filter(cluster => clusterRoleIds(cluster.members).length > 1)) {
      const key = cluster.members.map(point => point.posting_id).sort().join("|");
      next.add(key);
      let entry = markerRegistry.current.get(key);
      if (!entry) {
        const button = document.createElement("button");
        button.type = "button";
        button.className = "globe-cluster";
        button.setAttribute("aria-controls", "globe-rail");
        const marker = new Marker({ element: button }).setLngLat([cluster.anchor.lng, cluster.anchor.lat]).addTo(map);
        entry = { marker, button, lng: cluster.anchor.lng, lat: cluster.anchor.lat, ids: [] };
        markerRegistry.current.set(key, entry);
      }
      const { button } = entry;
      const ids = clusterRoleIds(cluster.members);
      entry.ids = ids;
      const place = clusterPlace(cluster.members);
      button.classList.toggle("globe-cluster-hovered", hoverIdRef.current !== null && ids.includes(hoverIdRef.current));
      button.classList.toggle("globe-cluster-stack", clusterIsStack(cluster.members));
      button.classList.toggle("globe-cluster-active", ids.length === bubbleIds.length && ids.every(id => bubbleIds.includes(id)));
      if (pulseSelection) {
        const selectedHere = cluster.members.some(point => point.posting_id === selected);
        button.classList.toggle("globe-cluster-selected", selectedHere);
        if (selectedHere) pulsedSelection.current = selected;
      } else if (!selected) button.classList.remove("globe-cluster-selected");
      button.setAttribute("aria-label", `${ids.length} ${ids.length === 1 ? "role" : "roles"} near ${place.replace(/^Near /, "")}`);
      button.textContent = String(ids.length);
      const bestScore = clusterScore(cluster);
      button.dataset.unscored = String(bestScore === null);
      button.style.setProperty("--cluster-size", `${ids.length < 10 ? 32 : ids.length < 100 ? 38 : 44}px`);
      button.onmouseenter = () => setHoveredBubble({ count: ids.length, place });
      button.onmouseleave = () => setHoveredBubble(null);
      button.style.setProperty("--cluster-color", scoreCss(bestScore));
      if (entry.lng !== cluster.anchor.lng || entry.lat !== cluster.anchor.lat) {
        entry.marker.setLngLat([cluster.anchor.lng, cluster.anchor.lat]);
        entry.lng = cluster.anchor.lng; entry.lat = cluster.anchor.lat;
      }
      button.onclick = event => {
        event.stopPropagation();
        activateCluster(cluster);
      };
    }
    for (const [key, entry] of markerRegistry.current) if (!next.has(key)) { setHoveredBubble(null); entry.marker.remove(); markerRegistry.current.delete(key); }
  }, [clusters, selected, ready, canInteract, bubbleIds, darkMap, hoverPoint]);
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
    moveToLocation(map, location, points, resetting, !initial && !reducedMotion());
  }, [active, ready, dataReady, location, points, cameraAction]);
  const focused = hovered && points.some(point => point.posting_id === hovered.posting_id) ? hovered : selectedPoint;
  return <section className="job-globe-shell" aria-label="Role locations globe">
    <div ref={globeRoot} onPointerLeave={() => hoverPoint(null)} className="job-globe">
      <div ref={container} style={{ position: "absolute", inset: 0, width: "100%", height: "100%" }} />
      {ready && <div className="globe-controls" role="group" aria-label="Globe controls">
        <button type="button" aria-label="Zoom in" disabled={zoomBounds.atMax} onClick={() => mapRef.current?.zoomIn({ duration: reducedMotion() ? 0 : 300 })}><Plus aria-hidden="true" /></button>
        <button type="button" aria-label="Zoom out" disabled={zoomBounds.atMin} onClick={() => mapRef.current?.zoomOut({ duration: reducedMotion() ? 0 : 300 })}><Minus aria-hidden="true" /></button>
        <span className="globe-controls-divider" aria-hidden="true" />
        <div className="globe-controls-location"><button type="button" className="maplibregl-ctrl-location" aria-label={locationLabel} title="Job Radar does not store your location. CARTO receives map tiles for the displayed area." onClick={locate}><LocateFixed aria-hidden="true" /></button><span className="maplibregl-ctrl-location-status" role="status" aria-live="polite" /></div>
        {fullscreenAvailable && <button type="button" aria-label={fullscreen ? "Exit full screen" : "Full screen"} onClick={() => { if (fullscreen) { if (document.exitFullscreen) void document.exitFullscreen().catch(() => {}); } else if (globeRoot.current?.requestFullscreen) void globeRoot.current.requestFullscreen().catch(() => {}); }}>{fullscreen ? <Minimize2 aria-hidden="true" /> : <Maximize2 aria-hidden="true" />}</button>}
      </div>}
      {!ready && <p className="pointer-events-none absolute left-4 top-4 rounded-md bg-slate-950/80 px-2 py-1 text-xs text-slate-200">{dataReady ? "Preparing the globe…" : "Loading map…"}</p>}
      {ready && showDragHint && <p className="pointer-events-none absolute left-4 top-4 rounded-md bg-slate-950/80 px-2 py-1 text-xs text-slate-200">Drag to spin · scroll to zoom</p>}
      {hoveredBubble && <div className="pointer-events-none absolute bottom-16 left-3 z-10 rounded-xl border bg-card/95 p-3 text-xs shadow-lg" role="tooltip">{hoveredBubble.count} roles near {hoveredBubble.place.replace(/^Near /, "")}<p className="mt-1 text-muted-foreground">Click to list them</p></div>}
      {focused && !hoveredBubble && !(hiddenFocusedSelection?.selected === selected && hiddenFocusedSelection.request === selectionRequest) && <div className="absolute bottom-16 left-3 z-10 max-w-64 rounded-xl border bg-card/95 p-3 text-xs shadow-lg" data-globe-posting={focused.posting_id} data-globe-hover={hovered?.posting_id} aria-live="polite"><p>{focused.job.company} · {focused.job.score === null ? "Unscored" : `${focused.job.score} fit`}</p><p className="mt-1 font-medium">{focused.job.title}</p><p className="mt-1">{pointLabel(focused)}</p><p className="mt-1 break-all">Source: {focused.source}</p></div>}
    </div>
  </section>;
}
