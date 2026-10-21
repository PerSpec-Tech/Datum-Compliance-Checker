import { useState } from "react";
import type { Edge, EdgeKind, RoadWidthBasis } from "../../api/types";

export interface EdgeTag {
  kind?: EdgeKind | null;
  road_width_m?: number | null;
  road_width_basis?: RoadWidthBasis | null;
}

// Line weight carries meaning as in a drawing set (guidelines 9): road heavy, neighbour regular,
// open space regular dashed, untagged hairline dashed.
const KIND_STYLE: Record<EdgeKind | "none", { stroke: string; label: string; weight: number; dash?: boolean }> = {
  road: { stroke: "var(--text-primary)", label: "road", weight: 2.5 },
  neighbour: { stroke: "var(--text-secondary)", label: "neighbour", weight: 1.5 },
  open_space: { stroke: "var(--text-secondary)", label: "open space", weight: 1.5, dash: true },
  none: { stroke: "var(--text-tertiary)", label: "not tagged", weight: 0.75, dash: true },
};

// P6.5: the plot boundary and building footprint drawn from the model; click a side to tag it.
export default function EdgePlan({
  edges,
  footprint,
  tags,
  onChange,
}: {
  edges: Edge[];
  footprint: number[][] | null;
  tags: Record<string, EdgeTag>;
  onChange: (tags: Record<string, EdgeTag>) => void;
}) {
  const [active, setActive] = useState<string | null>(edges[0]?.id ?? null);
  const pts = edges.flatMap((e) => [e.a, e.b]).concat(footprint ?? []);
  if (pts.length === 0) return <p className="text-sm text-fg-2">the model has no plot boundary.</p>;
  const xs = pts.map((p) => p[0]);
  const ys = pts.map((p) => p[1]);
  const [minX, maxX, minY, maxY] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const span = Math.max(maxX - minX, maxY - minY) || 1;
  const pad = span * 0.18;
  // SVG y grows downwards; flip so north (model +Y) is up.
  const P = (p: number[]) => `${p[0] - minX + pad},${maxY - p[1] + pad}`;
  const size = span + pad * 2;
  const tag = (id: string) => tags[id] ?? {};
  const set = (id: string, patch: EdgeTag) => onChange({ ...tags, [id]: { ...tag(id), ...patch } });
  const cur = active ? tag(active) : null;

  return (
    <div className="grid gap-4 md:grid-cols-[minmax(0,1fr)_16rem]">
      <svg viewBox={`0 0 ${size} ${size}`} className="aspect-square w-full rounded-md border border-line-subtle bg-surface-low">
        {footprint && (
          <polygon points={footprint.map(P).join(" ")} fill="var(--bg-surface-raised)" stroke="var(--border-strong)" strokeWidth={span * 0.004} />
        )}
        {edges.map((e) => {
          const k = (tag(e.id).kind ?? "none") as EdgeKind | "none";
          const [ax, ay] = P(e.a).split(",").map(Number);
          const [bx, by] = P(e.b).split(",").map(Number);
          const isActive = e.id === active;
          const w = tag(e.id).road_width_m;
          return (
            <g key={e.id} onClick={() => setActive(e.id)} className="cursor-pointer">
              <line x1={ax} y1={ay} x2={bx} y2={by} stroke="transparent" strokeWidth={span * 0.08} />
              <line
                x1={ax}
                y1={ay}
                x2={bx}
                y2={by}
                stroke={KIND_STYLE[k].stroke}
                strokeWidth={span * 0.008 * KIND_STYLE[k].weight * (isActive ? 1.6 : 1)}
                strokeLinecap="square"
                strokeDasharray={KIND_STYLE[k].dash ? `${span * 0.03} ${span * 0.02}` : undefined}
              />
              <text
                x={(ax + bx) / 2}
                y={(ay + by) / 2}
                dy={-span * 0.035}
                textAnchor="middle"
                fontSize={span * 0.045}
                fill="var(--text-primary)" fontFamily="JetBrains Mono, monospace"
                fontWeight={isActive ? 700 : 400}
              >
                {e.id}
                {k === "road" && w ? ` · ${w} m` : ""}
              </text>
            </g>
          );
        })}
        <text x={size - pad * 0.4} y={pad * 0.6} fontSize={span * 0.05} textAnchor="end" fill="var(--text-secondary)" fontFamily="JetBrains Mono, monospace">
          N ↑
        </text>
      </svg>

      {active && cur && (
        <div className="space-y-3">
          <p className="h2">
            side <span className="font-mono">{active}</span>
          </p>
          <div>
            <span className="label">what is on this side</span>
            <div className="flex flex-wrap gap-1.5">
              {(["road", "neighbour", "open_space"] as EdgeKind[]).map((k) => (
                <button
                  key={k}
                  type="button"
                  onClick={() => set(active, { kind: k })}
                  className={`h-8 rounded-sm border px-2.5 text-sm transition-colors ${cur.kind === k ? "border-fg bg-surface-raised text-fg" : "border-line text-fg-2 hover:border-line-strong hover:text-fg"}`}
                >
                  {KIND_STYLE[k].label}
                </button>
              ))}
            </div>
          </div>
          {cur.kind === "road" && (
            <>
              <label className="block">
                <span className="label">road width (m)</span>
                <input
                  className="input"
                  type="number"
                  min={0}
                  step={0.5}
                  value={cur.road_width_m ?? ""}
                  onChange={(e) => set(active, { road_width_m: e.target.value === "" ? null : Number(e.target.value) })}
                />
              </label>
              <label className="block">
                <span className="label">width basis</span>
                <select
                  className="input"
                  value={cur.road_width_basis ?? ""}
                  onChange={(e) => set(active, { road_width_basis: (e.target.value || null) as RoadWidthBasis | null })}
                >
                  <option value="">Choose…</option>
                  <option value="development_plan">Development Plan (proposed) width</option>
                  <option value="existing">Existing width</option>
                </select>
              </label>
              <p className="meta">UDCPR margins use the Development Plan width where one is proposed.</p>
            </>
          )}
          <div className="flex gap-2 pt-1">
            {edges.map((e) => (
              <button
                key={e.id}
                type="button"
                onClick={() => setActive(e.id)}
                className={`h-1.5 flex-1 ${e.id === active ? "outline outline-1 outline-offset-2 outline-fg-2" : ""}`}
                style={{ background: KIND_STYLE[(tag(e.id).kind ?? "none") as EdgeKind | "none"].stroke }}
                title={e.id}
              />
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
