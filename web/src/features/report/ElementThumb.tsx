import type { DrawingFloor } from "../../api/client";
import type { BuildingModel } from "../../api/types";
import type { Group } from "./groups";

// P12.5: a small plan cropped to one element, the element in red. Drawn from the model (rooms,
// plot, footprint) plus, for a 2D drawing, the floor's own lines. Doors, stairs and flats have no
// outline of their own, so the rooms they belong to are shown instead.

type Pt = number[];
interface Target {
  level: string | null;
  polys: Pt[][];
  segs: [Pt, Pt][];
  note?: string;
}

function target(model: BuildingModel, g: Group): Target | null {
  const room = (id: string | null | undefined) => model.spaces.find((s) => s.id === id);
  const ground = [...model.levels].sort((a, b) => a.elevation_m - b.elevation_m)[0]?.id ?? null;
  switch (g.kind) {
    case "spaces": {
      const s = room(g.id);
      return s?.polygon ? { level: s.level_id, polys: [s.polygon], segs: [] } : null;
    }
    case "doors": {
      const d = model.doors.find((x) => x.id === g.id);
      const rooms = [room(d?.from_space_id), room(d?.to_space_id)].filter((s) => s?.polygon);
      return rooms.length ? { level: d?.level_id ?? rooms[0]!.level_id, polys: rooms.map((s) => s!.polygon!), segs: [], note: "rooms the door joins" } : null;
    }
    case "stairs": {
      const st = model.stairs.find((x) => x.id === g.id);
      const s = model.spaces.find((x) => x.level_id === st?.base_level_id && x.usage.value === "stair" && x.polygon);
      return s ? { level: s.level_id, polys: [s.polygon!], segs: [] } : null;
    }
    case "units": {
      const u = model.units.find((x) => x.id === g.id);
      const rooms = model.spaces.filter((s) => s.level_id === u?.level_id && s.polygon && u && (s.name === u.name || s.name.startsWith(`${u.name} `)));
      return rooms.length ? { level: u!.level_id, polys: rooms.map((s) => s.polygon!), segs: [] } : null;
    }
    case "site.edges": {
      const e = model.site.edges.find((x) => x.id === g.id);
      return e ? { level: ground, polys: [], segs: [[e.a, e.b]] } : null;
    }
    default: {
      const fp = model.building.footprint;
      return fp ? { level: ground, polys: [fp], segs: [] } : null;
    }
  }
}

export default function ElementThumb({
  model,
  group,
  floors,
  width = 240,
  height = 170,
}: {
  model: BuildingModel;
  group: Group;
  floors?: DrawingFloor[];
  width?: number;
  height?: number;
}) {
  const t = target(model, group);
  if (!t) return null;

  const num = Number(/^L(-?\d+)$/.exec(t.level ?? "")?.[1] ?? NaN);
  const sheet = floors?.find((f) => f.nums.includes(num));
  const rooms = model.spaces.filter((s) => s.level_id === t.level && s.polygon);
  const site = model.site.boundary ?? [];
  const whole = group.kind === "building" || group.kind === "site.edges" || group.kind === "site";

  // Crop: the element plus some context, never tighter than 6 m.
  const pts = [...t.polys.flat(), ...t.segs.flat(), ...(whole ? site : [])];
  const xs = pts.map((p) => p[0]), ys = pts.map((p) => p[1]);
  let [x0, x1, y0, y1] = [Math.min(...xs), Math.max(...xs), Math.min(...ys), Math.max(...ys)];
  const pad = Math.max(3, Math.max(x1 - x0, y1 - y0) * 0.45);
  [x0, x1, y0, y1] = [x0 - pad, x1 + pad, y0 - pad, y1 + pad];
  // match the thumbnail's aspect so nothing is letterboxed
  const want = width / height;
  if ((x1 - x0) / (y1 - y0) < want) {
    const w = (y1 - y0) * want, cx = (x0 + x1) / 2;
    [x0, x1] = [cx - w / 2, cx + w / 2];
  } else {
    const h = (x1 - x0) / want, cy = (y0 + y1) / 2;
    [y0, y1] = [cy - h / 2, cy + h / 2];
  }
  const k = width / (x1 - x0); // px per metre
  const X = (x: number) => (x - x0) * k;
  const Y = (y: number) => (y1 - y) * k;
  const P = (p: Pt) => `${X(p[0]).toFixed(1)},${Y(p[1]).toFixed(1)}`;
  const flat = (a: number[]) => {
    let d = "";
    for (let i = 0; i < a.length; i += 2) d += `${i ? "L" : "M"}${X(a[i]).toFixed(1)} ${Y(a[i + 1]).toFixed(1)}`;
    return d;
  };
  const red = "var(--danger)";
  const bar = [1, 2, 5, 10, 20].find((m) => m * k > width / 6) ?? 20;

  return (
    <svg width={width} height={height} viewBox={`0 0 ${width} ${height}`} className="shrink-0 border border-line-subtle bg-surface-low" role="img" aria-label={`${group.name} on the plan`}>
      {site.length > 2 && <polygon points={site.map(P).join(" ")} fill="none" stroke="var(--draw-fine)" strokeWidth={0.8} />}
      {t.polys.map((p, i) => (
        <polygon key={`h${i}`} points={p.map(P).join(" ")} fill={red} fillOpacity={0.28} />
      ))}
      {sheet ? (
        <g>
          {sheet.fills.map((f, i) => (
            <path key={`f${i}`} d={flat(f) + "Z"} fill="var(--draw-wall)" fillRule="evenodd" />
          ))}
          {(["door", "window", "stair", "wall"] as const)
            .filter((c) => sheet.paths[c])
            .map((c) => (
              <path key={c} d={sheet.paths[c].map(flat).join("")} fill="none" stroke={c === "wall" ? "var(--draw-wall)" : "var(--draw-line)"} strokeWidth={c === "wall" ? 1.2 : 0.6} />
            ))}
        </g>
      ) : (
        rooms.map((s) => <polygon key={s.id} points={s.polygon!.map(P).join(" ")} fill="none" stroke="var(--draw-line)" strokeWidth={0.8} />)
      )}
      {model.building.footprint && whole && (
        <polygon points={model.building.footprint.map(P).join(" ")} fill="none" stroke="var(--draw-line)" strokeWidth={1} />
      )}
      {t.polys.map((p, i) => (
        <polygon key={`o${i}`} points={p.map(P).join(" ")} fill="none" stroke={red} strokeWidth={1.8} />
      ))}
      {t.segs.map(([a, b], i) => (
        <line key={`s${i}`} x1={X(a[0])} y1={Y(a[1])} x2={X(b[0])} y2={Y(b[1])} stroke={red} strokeWidth={4} strokeLinecap="round" />
      ))}
      <g fontFamily="JetBrains Mono, monospace" fontSize={9} fill="var(--text-tertiary)">
        <line x1={8} y1={height - 8} x2={8 + bar * k} y2={height - 8} stroke="var(--text-tertiary)" strokeWidth={1} />
        <text x={12 + bar * k} y={height - 5}>
          {bar} m
        </text>
        {t.note && (
          <text x={width - 6} y={height - 5} textAnchor="end" paintOrder="stroke" stroke="var(--bg-surface-low)" strokeWidth={3}>
            {t.note}
          </text>
        )}
      </g>
    </svg>
  );
}
