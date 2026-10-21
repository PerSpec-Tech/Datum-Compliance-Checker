import { useEffect, useMemo, useRef, useState, type PointerEvent, type WheelEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type DrawingFloor } from "../../api/client";
import type { BuildingModel, Status } from "../../api/types";
import { STATUS_META, StatusMark } from "../../components/ui";

// P10.5: the report's view for 2D drawings. The drawing itself (walls, doors, windows, furniture,
// dimensions, texts) is the base; the check's results are a translucent layer on the rooms.
// Line weight carries meaning (guidelines §9); colours come from the theme tokens.

const STROKE: Record<string, { color: string; width: number; dash?: string }> = {
  wall: { color: "var(--draw-wall)", width: 1.6 },
  door: { color: "var(--draw-line)", width: 0.8 },
  window: { color: "var(--draw-line)", width: 0.8 },
  stair: { color: "var(--draw-line)", width: 0.8 },
  furniture: { color: "var(--draw-fine)", width: 0.6 },
  dim: { color: "var(--draw-fine)", width: 0.5 },
  room: { color: "var(--draw-fine)", width: 0.4 },
  anno: { color: "var(--draw-line)", width: 0.6 },
};
const ORDER = ["room", "furniture", "dim", "anno", "stair", "window", "door", "wall"];
const hex = (n: number) => `#${n.toString(16).padStart(6, "0")}`;

export default function PlanViewer({
  model,
  projectId,
  statusById,
  selectedId,
  onPick,
}: {
  model: BuildingModel;
  projectId: string;
  statusById: Map<string, Status>;
  selectedId: string | null;
  onPick?: (kind: string, id: string) => void;
}) {
  const drawing = useQuery({ queryKey: ["drawing", projectId], queryFn: () => api.drawing(projectId), retry: false, staleTime: Infinity });
  const levels = useMemo(() => [...model.levels].sort((a, b) => a.elevation_m - b.elevation_m), [model]);
  const failsOn = (lv: string) => model.spaces.filter((s) => s.level_id === lv && statusById.get(s.id) === "fail").length;
  const selectedLevel = model.spaces.find((s) => s.id === selectedId)?.level_id;
  const [level, setLevel] = useState(levels.find((l) => failsOn(l.id) > 0)?.id ?? levels[0]?.id);
  const shown = selectedLevel ?? level;
  const [hover, setHover] = useState<string | null>(null);
  const [cursor, setCursor] = useState<[number, number] | null>(null);
  // View: a viewBox in svg units; null = fitted. Scroll zooms at the cursor, drag pans.
  const [view, setView] = useState<[number, number, number, number] | null>(null);
  const drag = useRef<{ x: number; y: number; v: [number, number, number, number] } | null>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  useEffect(() => setView(null), [shown]);
  useEffect(() => {
    // Wheel over the plan zooms it, not the page (React's wheel listener is passive).
    const el = svgRef.current;
    const stop = (e: globalThis.WheelEvent) => e.preventDefault();
    el?.addEventListener("wheel", stop, { passive: false });
    return () => el?.removeEventListener("wheel", stop);
  });

  const num = Number(/^L(-?\d+)$/.exec(shown ?? "")?.[1] ?? NaN);
  const sheet: DrawingFloor | undefined = drawing.data?.floors.find((f) => f.nums.includes(num));

  const site = model.site.boundary ?? [];
  const spaces = model.spaces.filter((s) => s.level_id === shown && s.polygon);
  const pts = [...site, ...(model.building.footprint ?? []), ...spaces.flatMap((s) => s.polygon ?? [])];
  if (pts.length === 0) return <div className="panel grid h-full min-h-[320px] place-items-center text-sm text-fg-2">nothing to draw</div>;
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const span = Math.max(x1 - x0, y1 - y0) || 1;
  const pad = span * 0.08;
  const W = x1 - x0 + pad * 2;
  const H = y1 - y0 + pad * 2;
  const X = (x: number) => x - x0 + pad;
  const Y = (y: number) => y1 - y + pad; // north up
  const P = (p: number[]) => `${X(p[0])},${Y(p[1])}`;
  const flat = (a: number[]) => {
    let d = "";
    for (let i = 0; i < a.length; i += 2) d += `${i ? "L" : "M"}${X(a[i]).toFixed(3)} ${Y(a[i + 1]).toFixed(3)}`;
    return d;
  };
  // Fit: the drawing of this floor (plus a margin) when there is one, else the whole plot.
  let fit: [number, number, number, number] = [0, 0, W, H];
  if (sheet) {
    const all = Object.values(sheet.paths).flat().concat(sheet.fills);
    let a = Infinity, b = Infinity, c = -Infinity, e = -Infinity;
    for (const line of all)
      for (let i = 0; i < line.length; i += 2) {
        a = Math.min(a, X(line[i])); c = Math.max(c, X(line[i]));
        b = Math.min(b, Y(line[i + 1])); e = Math.max(e, Y(line[i + 1]));
      }
    if (Number.isFinite(a)) {
      const m = Math.max(c - a, e - b) * 0.06;
      fit = [a - m, b - m, c - a + 2 * m, e - b + 2 * m];
    }
  }
  const vb = view ?? fit;
  const zoom = W / vb[2];
  const px = vb[2] / 600; // ~one screen pixel in drawing units

  function toSvg(clientX: number, clientY: number): [number, number] {
    const r = svgRef.current!.getBoundingClientRect();
    const k = Math.max(vb[2] / r.width, vb[3] / r.height);
    const ox = (r.width * k - vb[2]) / 2;
    const oy = (r.height * k - vb[3]) / 2;
    return [vb[0] + (clientX - r.left) * k - ox, vb[1] + (clientY - r.top) * k - oy];
  }
  function onWheel(e: WheelEvent) {
    const [sx, sy] = toSvg(e.clientX, e.clientY);
    const f = e.deltaY > 0 ? 1.18 : 1 / 1.18;
    const w = Math.min(Math.max(vb[2] * f, W / 40), W * 1.5);
    const h = (vb[3] / vb[2]) * w;
    setView([sx - ((sx - vb[0]) * w) / vb[2], sy - ((sy - vb[1]) * h) / vb[3], w, h]);
  }
  function onDown(e: PointerEvent) {
    drag.current = { x: e.clientX, y: e.clientY, v: vb };
    (e.target as Element).setPointerCapture?.(e.pointerId);
  }
  function onDrag(e: PointerEvent) {
    const d = drag.current;
    if (!d) return;
    const r = svgRef.current!.getBoundingClientRect();
    const k = Math.max(d.v[2] / r.width, d.v[3] / r.height);
    setView([d.v[0] - (e.clientX - d.x) * k, d.v[1] - (e.clientY - d.y) * k, d.v[2], d.v[3]]);
  }

  return (
    <div className="panel relative flex h-full min-h-[360px] flex-col overflow-hidden bg-surface-low">
      <div className="flex flex-wrap gap-1 border-b border-line-subtle p-2">
        {levels.map((l) => {
          const f = failsOn(l.id);
          return (
            <button
              key={l.id}
              onClick={() => setLevel(l.id)}
              className={`flex h-7 items-center gap-1.5 rounded-sm border px-2 text-xs ${
                l.id === shown ? "border-fg bg-surface-raised text-fg" : "border-line-subtle text-fg-2 hover:text-fg"
              }`}
            >
              {l.name}
              {f > 0 && <span className="font-mono text-danger">{f}</span>}
            </button>
          );
        })}
      </div>
      <svg
        ref={svgRef}
        viewBox={vb.join(" ")}
        className="min-h-0 w-full flex-1 cursor-grab touch-none active:cursor-grabbing"
        onWheel={onWheel}
        onPointerDown={onDown}
        onPointerUp={() => (drag.current = null)}
        onDoubleClick={() => setView(null)}
        onPointerMove={(e) => {
          onDrag(e);
          const [sx, sy] = toSvg(e.clientX, e.clientY);
          setCursor([sx - pad + x0, y1 - (sy - pad)]);
        }}
        onMouseLeave={() => {
          setCursor(null);
          setHover(null);
          drag.current = null;
        }}
      >
        {/* plot and roads, from the model */}
        {site.length > 0 && <polygon points={site.map(P).join(" ")} fill="var(--bg-surface)" stroke="var(--draw-fine)" strokeWidth={px} />}
        {model.site.edges.map((e) => {
          const st = statusById.get(e.id);
          const road = e.kind.value === "road";
          return (
            <g key={e.id}>
              <line
                x1={X(e.a[0])}
                y1={Y(e.a[1])}
                x2={X(e.b[0])}
                y2={Y(e.b[1])}
                stroke={st === "fail" ? hex(STATUS_META.fail.hex) : road ? "var(--text-primary)" : "var(--draw-fine)"}
                strokeWidth={px * (road ? 3 : 1.2)}
                strokeDasharray={e.kind.source === "inferred" ? `${px * 6} ${px * 4}` : undefined}
              />
              {road && (
                <text x={(X(e.a[0]) + X(e.b[0])) / 2} y={(Y(e.a[1]) + Y(e.b[1])) / 2 + px * 16} fontSize={px * 10} textAnchor="middle" fill="var(--text-tertiary)" fontFamily="JetBrains Mono, monospace">
                  road {e.road_width_m.value ?? "?"} m
                </text>
              )}
            </g>
          );
        })}

        {/* results: a translucent wash on each room, under the drawing's lines */}
        {spaces.map((s) => {
          const st = statusById.get(s.id);
          const sel = s.id === selectedId;
          return (
            <polygon
              key={s.id}
              points={s.polygon!.map(P).join(" ")}
              fill={st ? hex(STATUS_META[st].hex) : sheet ? "transparent" : "var(--bg-surface-raised)"}
              fillOpacity={st === "fail" ? 0.32 : st === "pass" ? 0.07 : st ? 0.18 : 1}
              stroke={sel ? "var(--text-primary)" : st === "unverifiable" ? "var(--text-secondary)" : "none"}
              strokeWidth={px * (sel ? 3 : 1)}
              strokeDasharray={st && STATUS_META[st].dashed ? `${px * 5} ${px * 4}` : undefined}
              className="cursor-pointer"
              onMouseEnter={() => setHover(s.name)}
              onClick={() => onPick?.("spaces", s.id)}
            />
          );
        })}

        {/* the drawing itself */}
        {sheet ? (
          <g pointerEvents="none">
            {sheet.fills.map((f, i) => (
              <path key={`f${i}`} d={flat(f) + "Z"} fill="var(--draw-wall)" fillRule="evenodd" />
            ))}
            {ORDER.filter((c) => sheet.paths[c]).map((c) => (
              <path
                key={c}
                d={sheet.paths[c].map(flat).join("")}
                fill="none"
                stroke={STROKE[c]?.color ?? "var(--draw-line)"}
                strokeWidth={px * (STROKE[c]?.width ?? 0.6)}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}
            {sheet.texts.map(([x, y, h, rot, t, cls], i) => (
              <text
                key={`t${i}`}
                x={X(x)}
                y={Y(y)}
                fontSize={h * 1.35}
                textAnchor="middle"
                dominantBaseline="central"
                transform={rot ? `rotate(${-rot} ${X(x)} ${Y(y)})` : undefined}
                fill={cls === "room" ? "var(--text-primary)" : "var(--text-tertiary)"}
                fontFamily={cls === "room" ? "DM Sans, sans-serif" : "JetBrains Mono, monospace"}
              >
                {t}
              </text>
            ))}
          </g>
        ) : (
          spaces.map((s) => <polygon key={`o${s.id}`} points={s.polygon!.map(P).join(" ")} fill="none" stroke="var(--draw-line)" strokeWidth={px} pointerEvents="none" />)
        )}

        {model.building.footprint && !sheet && (
          <polygon points={model.building.footprint.map(P).join(" ")} fill="none" stroke="var(--draw-line)" strokeWidth={px} strokeDasharray={`${px * 5} ${px * 3}`} />
        )}


      </svg>
      {hover && (
        <div className="pointer-events-none absolute left-3 top-14 rounded-sm border border-line bg-surface-overlay px-2 py-1 text-xs">{hover}</div>
      )}
      <div className="pointer-events-none absolute right-3 top-14 flex flex-col items-center rounded-sm border border-line-subtle bg-surface px-1.5 py-1 text-fg-2">
        <svg width="12" height="16" viewBox="0 0 12 16" fill="none" stroke="currentColor" strokeWidth="1.25" aria-hidden>
          <path d="M6 1l4 13-4-3-4 3 4-13z" />
        </svg>
        <span className="font-mono text-2xs leading-3">N</span>
      </div>
      <div className="pointer-events-none absolute bottom-3 right-3 flex flex-col gap-1 rounded-sm border border-line-subtle bg-surface px-2 py-1.5">
        {(["fail", "unverifiable", "pass"] as Status[]).map((s) => (
          <StatusMark key={s} status={s} />
        ))}
      </div>
      <div className="readout pointer-events-none absolute left-3 top-14" hidden={!!hover}>
        {cursor ? `x ${cursor[0].toFixed(2)}  y ${cursor[1].toFixed(2)} m` : "x —  y — m"}  ·  {zoom.toFixed(1)}×
      </div>
    </div>
  );
}
