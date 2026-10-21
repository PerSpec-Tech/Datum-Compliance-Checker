import type { LivePack } from "../../api/types";

// P12.2: the margins the rules require, drawn on the plan (from the live pack of the last check).
// Buildable line dashed; per side the required margin, its clause and the actual gap; the part of
// the building outside the buildable line shaded red.

type Pt = number[];

function segDist(p: Pt, a: Pt, b: Pt): number {
  const dx = b[0] - a[0], dy = b[1] - a[1];
  const L = dx * dx + dy * dy || 1;
  const t = Math.max(0, Math.min(1, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / L));
  return Math.hypot(p[0] - a[0] - t * dx, p[1] - a[1] - t * dy);
}

/** Shortest distance between a plot side and the building outline (both directions). */
export function gapTo(a: Pt, b: Pt, ring: Pt[]): number {
  let d = Infinity;
  for (let i = 0; i < ring.length; i++) {
    const p = ring[i], q = ring[(i + 1) % ring.length];
    d = Math.min(d, segDist(p, a, b), segDist(a, p, q), segDist(b, p, q));
  }
  return d;
}

export default function SetbackLayer({
  pack,
  footprint,
  X,
  Y,
  px,
}: {
  pack: LivePack;
  footprint: Pt[] | null | undefined;
  X: (x: number) => number;
  Y: (y: number) => number;
  px: number;
}) {
  const P = (p: Pt) => `${X(p[0])},${Y(p[1])}`;
  const env = pack.envelope;
  const plot = pack.edges.map((e) => e.a);
  const cx = plot.reduce((s, p) => s + p[0], 0) / (plot.length || 1);
  const cy = plot.reduce((s, p) => s + p[1], 0) / (plot.length || 1);
  const red = "var(--danger)";
  return (
    <g pointerEvents="none" fontFamily="JetBrains Mono, monospace">
      {env && footprint && footprint.length > 2 && (
        <>
          <mask id="outside-envelope">
            <rect x="-1e5" y="-1e5" width="2e5" height="2e5" fill="white" />
            <polygon points={env.map(P).join(" ")} fill="black" />
          </mask>
          <polygon points={footprint.map(P).join(" ")} fill={red} fillOpacity={0.35} mask="url(#outside-envelope)" />
        </>
      )}
      {env && (
        <polygon
          points={env.map(P).join(" ")}
          fill="none"
          stroke="var(--text-secondary)"
          strokeWidth={px * 1.4}
          strokeDasharray={`${px * 8} ${px * 4}`}
        />
      )}
      {pack.edges.map((e) => {
        if (e.margin_m == null) return null;
        const mx = (e.a[0] + e.b[0]) / 2, my = (e.a[1] + e.b[1]) / 2;
        // inward unit normal: the side of the edge the plot centre is on
        let nx = -(e.b[1] - e.a[1]), ny = e.b[0] - e.a[0];
        const n = Math.hypot(nx, ny) || 1;
        nx /= n; ny /= n;
        if ((cx - mx) * nx + (cy - my) * ny < 0) { nx = -nx; ny = -ny; }
        const gap = footprint && footprint.length > 2 ? gapTo(e.a, e.b, footprint) : null;
        const short = gap != null && gap + 0.005 < e.margin_m;
        const at = [mx + nx * (e.margin_m / 2), my + ny * (e.margin_m / 2)];
        const ang = (Math.atan2(-(e.b[1] - e.a[1]), e.b[0] - e.a[0]) * 180) / Math.PI;
        const up = ang > 90 || ang < -90 ? ang + 180 : ang; // keep text upright
        return (
          <g key={e.edge_id}>
            <title>{`${e.kind ?? "side"}: ${e.margin_m.toFixed(2)} m required (${e.clause_ref ?? e.rule_id ?? "rule"})${gap != null ? `, ${gap.toFixed(2)} m provided` : ""}`}</title>
            <line
              x1={X(mx)} y1={Y(my)} x2={X(mx + nx * e.margin_m)} y2={Y(my + ny * e.margin_m)}
              stroke={short ? red : "var(--text-secondary)"} strokeWidth={px}
            />
            <text
              x={X(at[0])} y={Y(at[1])} fontSize={px * 10} textAnchor="middle" dominantBaseline="central"
              transform={`rotate(${up} ${X(at[0])} ${Y(at[1])})`}
              fill={short ? red : "var(--text-secondary)"}
              paintOrder="stroke" stroke="var(--bg-surface-low)" strokeWidth={px * 3}
            >
              {`≥ ${e.margin_m.toFixed(2)} m`}
              {gap != null ? (short ? ` · ${gap.toFixed(2)} (−${(e.margin_m - gap).toFixed(2)})` : ` · ${gap.toFixed(2)}`) : ""}
            </text>
          </g>
        );
      })}
    </g>
  );
}
