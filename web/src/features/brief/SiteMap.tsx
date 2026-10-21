import { useEffect, useMemo, useRef, useState } from "react";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import type { BuildingModel } from "../../api/types";
import { Icon } from "../../components/ui";
import { css } from "../../lib/theme";
import type { LatLon } from "./MapPin";

// P12.3: put the drawing on the map. The plan (model coordinates, metres) is placed by a point and a
// rotation; the plot is the model's own, or drawn here corner by corner, or typed as a rectangle.
// Each side is then tagged road / neighbour / open space. Everything here becomes declared brief
// answers: project.location, site.placement, site.boundary (when drawn), site.edges.

export interface Placement {
  lat: number;
  lon: number;
  rotation_deg: number; // anticlockwise: the drawing's +y turned this far from north towards west
  anchor: [number, number]; // the model point that sits at lat/lon (the building's centre)
}
export type EdgeTag = { kind: "road" | "neighbour" | "open_space" | null; road_width_m: number | null };
export interface SiteDraft {
  placement: Placement | null;
  boundary: number[][] | null; // drawn here; null = the model's own plot
  tags: Record<string, EdgeTag>;
}

const M = 111_320; // metres per degree of latitude
const PUNE = { lat: 18.5204, lon: 73.8567 };

export function toGeo(p: number[], pl: Placement): [number, number] {
  const t = (pl.rotation_deg * Math.PI) / 180;
  const dx = p[0] - pl.anchor[0], dy = p[1] - pl.anchor[1];
  const x = dx * Math.cos(t) - dy * Math.sin(t);
  const y = dx * Math.sin(t) + dy * Math.cos(t);
  return [pl.lat + y / M, pl.lon + x / (M * Math.cos((pl.lat * Math.PI) / 180))];
}

export function toModel(ll: L.LatLng, pl: Placement): number[] {
  const t = (pl.rotation_deg * Math.PI) / 180;
  const y = (ll.lat - pl.lat) * M;
  const x = (ll.lng - pl.lon) * M * Math.cos((pl.lat * Math.PI) / 180);
  return [+(pl.anchor[0] + x * Math.cos(t) + y * Math.sin(t)).toFixed(3), +(pl.anchor[1] - x * Math.sin(t) + y * Math.cos(t)).toFixed(3)];
}

/** The plot's sides as the check will see them: the drawn plot's, else the model's. */
export function sides(model: BuildingModel, draft: SiteDraft) {
  if (draft.boundary)
    return draft.boundary.map((a, i) => ({ id: `e${i + 1}`, a, b: draft.boundary![(i + 1) % draft.boundary!.length] }));
  return model.site.edges.map((e) => ({ id: e.id, a: e.a, b: e.b }));
}

export function tagOf(model: BuildingModel, draft: SiteDraft, id: string): EdgeTag {
  if (draft.tags[id]) return draft.tags[id];
  // The model's tags still apply while the plot is the model's (or the same drawn plot, merged in).
  const same = !draft.boundary || JSON.stringify(draft.boundary) === JSON.stringify(model.site.boundary);
  const e = same ? model.site.edges.find((x) => x.id === id) : undefined;
  return { kind: (e?.kind.value as EdgeTag["kind"]) ?? null, road_width_m: e?.road_width_m.value ?? null };
}

function centre(model: BuildingModel): [number, number] {
  const pts = model.building.footprint ?? model.site.boundary ?? model.spaces.flatMap((s) => s.polygon ?? []);
  if (!pts.length) return [0, 0];
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  return [(Math.min(...xs) + Math.max(...xs)) / 2, (Math.min(...ys) + Math.max(...ys)) / 2];
}

export function startPlacement(model: BuildingModel, at: LatLon): Placement {
  return { lat: at.lat, lon: at.lon, rotation_deg: 0, anchor: centre(model) };
}

type Mode = "place" | "draw";

export default function SiteMap({
  model,
  draft,
  onChange,
  center = PUNE,
  className = "h-[440px]",
}: {
  model: BuildingModel;
  draft: SiteDraft;
  onChange: (d: SiteDraft) => void;
  center?: LatLon;
  className?: string;
}) {
  const host = useRef<HTMLDivElement>(null);
  const map = useRef<L.Map | null>(null);
  const layer = useRef<L.LayerGroup | null>(null);
  const [mode, setMode] = useState<Mode>("place");
  const [drawing, setDrawing] = useState<L.LatLng[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [zoom, setZoom] = useState(draft.placement ? 18 : 12);
  const state = useRef({ draft, onChange, mode, drawing, model });
  state.current = { draft, onChange, mode, drawing, model };

  const footprint = model.building.footprint ?? null;
  const plot = draft.boundary ?? model.site.boundary ?? null;
  const edges = useMemo(() => sides(model, draft), [model, draft]);

  // The map itself, once.
  useEffect(() => {
    if (!host.current) return;
    const start = draft.placement ?? center;
    const m = L.map(host.current, { doubleClickZoom: false, zoomControl: false }).setView([start.lat, start.lon], draft.placement ? 18 : 12);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 20,
      maxNativeZoom: 19,
      className: "map-dark",
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors',
    }).addTo(m);
    L.control.zoom({ position: "bottomright" }).addTo(m);
    m.on("zoomend", () => setZoom(m.getZoom()));
    m.on("click", (e: L.LeafletMouseEvent) => {
      const s = state.current;
      if (s.mode === "draw") {
        setDrawing((d) => [...d, e.latlng]);
        return;
      }
      const pl = s.draft.placement ?? startPlacement(s.model, { lat: e.latlng.lat, lon: e.latlng.lng });
      s.onChange({ ...s.draft, placement: { ...pl, lat: +e.latlng.lat.toFixed(7), lon: +e.latlng.lng.toFixed(7) } });
    });
    m.on("dblclick", () => {
      if (state.current.mode === "draw") finishRef.current();
    });
    layer.current = L.layerGroup().addTo(m);
    map.current = m;
    return () => {
      m.remove();
      map.current = null;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Fly to a new placement made outside the map (address search).
  useEffect(() => {
    const m = map.current, pl = draft.placement;
    if (m && pl && !m.getBounds().pad(-0.15).contains([pl.lat, pl.lon])) m.setView([pl.lat, pl.lon], Math.max(m.getZoom(), 18));
  }, [draft.placement?.lat, draft.placement?.lon]); // eslint-disable-line react-hooks/exhaustive-deps

  // Draw the plan, the plot and its sides.
  useEffect(() => {
    const g = layer.current, m = map.current, pl = draft.placement;
    if (!g || !m) return;
    g.clearLayers();
    const ink = css("--text-primary") || "#f2f2f3";
    const fine = css("--text-secondary") || "#9a9aa1";
    if (pl) {
      if (plot) L.polygon(plot.map((p) => toGeo(p, pl)), { color: fine, weight: 1, fillOpacity: 0.06, interactive: false }).addTo(g);
      for (const s of model.spaces.filter((x) => x.polygon && x.level_id === model.levels[0]?.id))
        L.polygon(s.polygon!.map((p) => toGeo(p, pl)), { color: fine, weight: 0.6, fillOpacity: 0, interactive: false }).addTo(g);
      if (footprint) {
        const fp = L.polygon(footprint.map((p) => toGeo(p, pl)), {
          color: ink,
          weight: 2,
          fillColor: "#d22b10",
          fillOpacity: 0.18,
          className: mode === "place" ? "cursor-move" : "",
        }).addTo(g);
        fp.bindTooltip("drag to move", { direction: "top", opacity: 0.9 });
        fp.on("mousedown", (e: L.LeafletMouseEvent) => {
          if (state.current.mode !== "place") return;
          L.DomEvent.stop(e);
          m.dragging.disable();
          const from = e.latlng, base = state.current.draft.placement!;
          const move = (ev: L.LeafletMouseEvent) =>
            state.current.onChange({
              ...state.current.draft,
              placement: { ...base, lat: +(base.lat + ev.latlng.lat - from.lat).toFixed(7), lon: +(base.lon + ev.latlng.lng - from.lng).toFixed(7) },
            });
          m.on("mousemove", move);
          m.once("mouseup", () => {
            m.off("mousemove", move);
            m.dragging.enable();
          });
        });
      }
      edges.forEach((e) => {
        const t = tagOf(model, draft, e.id);
        const line = L.polyline([toGeo(e.a, pl), toGeo(e.b, pl)], {
          color: e.id === selected ? "#d22b10" : t.kind === "road" ? ink : fine,
          weight: e.id === selected ? 6 : t.kind === "road" ? 5 : 3,
          dashArray: t.kind ? undefined : "6 6",
        }).addTo(g);
        line.bindTooltip(`${e.id} · ${t.kind ? t.kind.replace("_", " ") : "untagged"}${t.kind === "road" ? ` ${t.road_width_m ?? "?"} m` : ""}`, { sticky: true });
        line.on("click", (ev: L.LeafletMouseEvent) => {
          if (state.current.mode !== "place") return;
          L.DomEvent.stop(ev);
          setSelected(e.id);
        });
      });
    }
    if (drawing.length) {
      L.polyline(drawing, { color: "#d22b10", weight: 2, dashArray: "4 4" }).addTo(g);
      drawing.forEach((p) => L.circleMarker(p, { radius: 3, color: "#d22b10", fillOpacity: 1 }).addTo(g));
    }
  }, [draft, plot, footprint, edges, selected, drawing, mode, model]);

  const finishRef = useRef(() => {});
  finishRef.current = () => {
    const pl = draft.placement;
    if (!pl || drawing.length < 3) return;
    onChange({ ...draft, boundary: drawing.map((p) => toModel(p, pl)), tags: {} });
    setDrawing([]);
    setMode("place");
  };

  const pl = draft.placement;
  const sel = selected ? edges.find((e) => e.id === selected) : undefined;
  const setTag = (id: string, t: Partial<EdgeTag>) =>
    onChange({ ...draft, tags: { ...draft.tags, [id]: { ...tagOf(model, draft, id), ...t } } });

  return (
    <div>
      <div className={`relative overflow-hidden rounded-md border border-line-subtle ${className}`}>
        <div ref={host} className={`absolute inset-0 ${mode === "draw" ? "cursor-crosshair" : ""}`} />
        <div className="absolute left-3 top-3 z-[500] flex gap-1">
          <button
            className={`btn-secondary h-7 bg-surface px-2.5 text-xs ${mode === "place" ? "border-fg text-fg" : ""}`}
            onClick={() => { setMode("place"); setDrawing([]); }} // prettier-ignore
          >
            <Icon name="move" size={14} /> place
          </button>
          <button
            className={`btn-secondary h-7 bg-surface px-2.5 text-xs ${mode === "draw" ? "border-fg text-fg" : ""}`}
            disabled={!pl}
            title={pl ? "Click each plot corner; double-click to finish" : "Place the drawing first"}
            onClick={() => { setMode("draw"); setDrawing([]); setSelected(null); }} // prettier-ignore
          >
            <Icon name="polygon" size={14} /> draw plot
          </button>
          {mode === "draw" && (
            <button className="btn-primary h-7 px-2.5 text-xs" disabled={drawing.length < 3} onClick={() => finishRef.current()}>
              <Icon name="check" size={14} /> done ({drawing.length})
            </button>
          )}
        </div>
        <div className="pointer-events-none absolute right-3 top-3 z-[500] flex flex-col items-center rounded-sm border border-line-subtle bg-surface px-1.5 py-1 text-fg-2">
          <svg width="12" height="16" viewBox="0 0 12 16" fill="none" stroke="currentColor" strokeWidth="1.25" aria-hidden>
            <path d="M6 1l4 13-4-3-4 3 4-13z" />
          </svg>
          <span className="font-mono text-2xs leading-3">N</span>
        </div>
        <div className="readout pointer-events-none absolute bottom-3 left-3 z-[500]">
          {mode === "draw"
            ? "click each corner of the plot · double-click to finish"
            : pl
              ? `${pl.lat.toFixed(5)}° N  ${pl.lon.toFixed(5)}° E  ·  ${pl.rotation_deg}°  ·  z${zoom}`
              : "click the map where the building stands"}
        </div>
      </div>

      {pl && (
        <div className="mt-3 grid gap-3 sm:grid-cols-[1fr_auto]">
          <label className="flex items-center gap-3 text-xs text-fg-2">
            <span className="w-14 shrink-0">rotate</span>
            <input
              type="range"
              min={-180}
              max={180}
              step={0.5}
              value={pl.rotation_deg}
              onChange={(e) => onChange({ ...draft, placement: { ...pl, rotation_deg: +e.target.value } })}
              className="w-full accent-[var(--text-primary)]"
            />
            <input
              type="number"
              className="input h-7 w-20 py-0 font-mono text-xs"
              value={pl.rotation_deg}
              step={0.5}
              onChange={(e) => onChange({ ...draft, placement: { ...pl, rotation_deg: +e.target.value || 0 } })}
            />
            °
          </label>
          {!plot && <PlotSize model={model} onPlot={(ring) => onChange({ ...draft, boundary: ring, tags: {} })} />}
          {draft.boundary && (
            <button className="btn-ghost h-7 text-xs" onClick={() => onChange({ ...draft, boundary: null, tags: {} })}>
              <Icon name="x" size={12} /> clear drawn plot
            </button>
          )}
        </div>
      )}

      {pl && edges.length > 0 && (
        <div className="panel mt-3 divide-y divide-line-subtle">
          {edges.map((e) => {
            const t = tagOf(model, draft, e.id);
            const len = Math.hypot(e.b[0] - e.a[0], e.b[1] - e.a[1]);
            return (
              <div
                key={e.id}
                className={`flex items-center gap-3 px-3 py-2 text-sm ${e.id === sel?.id ? "bg-surface-raised" : ""}`}
                onMouseEnter={() => setSelected(e.id)}
              >
                <span className="w-24 shrink-0 font-mono text-xs text-fg-2">
                  {e.id} · {len.toFixed(1)} m
                </span>
                <div className="flex gap-1">
                  {(["road", "neighbour", "open_space"] as const).map((k) => (
                    <button
                      key={k}
                      onClick={() => setTag(e.id, { kind: k })}
                      aria-pressed={t.kind === k}
                      className={`h-7 rounded-sm border px-2 text-xs ${t.kind === k ? "border-fg bg-surface-raised text-fg" : "border-line-subtle text-fg-2 hover:text-fg"}`}
                    >
                      <span className="flex items-center gap-1.5">
                        <Icon name={k === "road" ? "road" : k === "neighbour" ? "home" : "tree"} size={12} /> {k.replace("_", " ")}
                      </span>
                    </button>
                  ))}
                </div>
                {t.kind === "road" && (
                  <label className="ml-auto flex items-center gap-1.5 text-xs text-fg-2">
                    width
                    <input
                      type="number"
                      min={1}
                      step={0.5}
                      className="input h-7 w-16 py-0 font-mono text-xs"
                      value={t.road_width_m ?? ""}
                      onChange={(ev) => setTag(e.id, { road_width_m: ev.target.value ? +ev.target.value : null })}
                    />
                    m
                  </label>
                )}
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

// No plot in the drawing: type it from the 7/12 extract as a rectangle around the building.
function PlotSize({ model, onPlot }: { model: BuildingModel; onPlot: (ring: number[][]) => void }) {
  const [v, setV] = useState({ w: "", d: "", left: "", front: "" });
  const fp = model.building.footprint;
  if (!fp) return null;
  const x0 = Math.min(...fp.map((p) => p[0])), y0 = Math.min(...fp.map((p) => p[1]));
  const n = (s: string) => Number(s);
  const ok = n(v.w) > 0 && n(v.d) > 0 && v.left !== "" && v.front !== "";
  const field = (k: keyof typeof v, label: string) => (
    <label className="flex items-center gap-1 text-xs text-fg-2">
      {label}
      <input className="input h-7 w-14 py-0 font-mono text-xs" type="number" min={0} step={0.1} value={v[k]} onChange={(e) => setV({ ...v, [k]: e.target.value })} />
    </label>
  );
  return (
    <form
      className="flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        if (!ok) return;
        const ax = x0 - n(v.left), ay = y0 - n(v.front);
        onPlot([[ax, ay], [ax + n(v.w), ay], [ax + n(v.w), ay + n(v.d)], [ax, ay + n(v.d)]]);
      }}
      title="Plot width and depth, and the building's distance from its left and front (south) sides"
    >
      {field("w", "plot")}×{field("d", "")} m · gap {field("left", "left")} {field("front", "front")}
      <button className="btn-secondary h-7 px-2 text-xs" disabled={!ok}>
        <Icon name="check" size={12} /> set
      </button>
    </form>
  );
}
