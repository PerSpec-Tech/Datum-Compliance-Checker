import type { ReactNode } from "react";
import type { Source, Status } from "../api/types";

// Line icons, 1.5px stroke, no fills (guidelines §7).
const PATHS = {
  check: "M4 10.5l3.5 3.5L16 5.5",
  x: "M5 5l10 10M15 5L5 15",
  question: "M7.5 7.5a2.5 2.5 0 1 1 3.5 2.3c-.6.3-1 .8-1 1.5v.7M10 14.5v.5",
  info: "M10 9v5M10 6v.5",
  dash: "M5 10h10",
  upload: "M10 13V3m0 0L6 7m4-4l4 4M3 13v3h14v-3",
  pin: "M10 18s5-5.2 5-9a5 5 0 0 0-10 0c0 3.8 5 9 5 9zM10 10.5a1.5 1.5 0 1 0 0-3 1.5 1.5 0 0 0 0 3z",
  search: "M9 15a6 6 0 1 0 0-12 6 6 0 0 0 0 12zM13.5 13.5L17 17",
  cube: "M10 2l7 4v8l-7 4-7-4V6l7-4zM3 6l7 4 7-4M10 10v8",
  list: "M7 5h10M7 10h10M7 15h10M3 5h.5M3 10h.5M3 15h.5",
  book: "M4 3h9a3 3 0 0 1 3 3v11H7a3 3 0 0 1-3-3V3zM4 14a3 3 0 0 1 3-3h9",
  gauge: "M3 14a7 7 0 1 1 14 0M10 14l3-4",
  link: "M8 12l4-4M7 9l-2 2a2.8 2.8 0 0 0 4 4l2-2M13 11l2-2a2.8 2.8 0 0 0-4-4L9 7",
  arrow: "M4 10h12m0 0l-4-4m4 4l-4 4",
  back: "M16 10H4m0 0l4-4m-4 4l4 4",
  download: "M10 3v10m0 0l-4-4m4 4l4-4M3 15v2h14v-2",
  plug: "M7 2v4M13 2v4M5 6h10v3a5 5 0 0 1-10 0V6zM10 14v4",
  layers: "M10 3l7 4-7 4-7-4 7-4zM3 11l7 4 7-4",
  chevron: "M6 8l4 4 4-4",
  refresh: "M16 10a6 6 0 1 1-1.8-4.3M16 3v3.5h-3.5",
  edit: "M4 16h3l9-9-3-3-9 9v3z",
  move: "M10 2v16M2 10h16M7.5 4.5L10 2l2.5 2.5M7.5 15.5L10 18l2.5-2.5M4.5 7.5L2 10l2.5 2.5M15.5 7.5L18 10l-2.5 2.5",
  polygon: "M4 15L6 4l10 3-1 9zM4 15h.01M6 4h.01M16 7h.01M15 16h.01",
  road: "M7 3L4 17M13 3l3 14M10 4v2M10 9v2M10 14v2",
  home: "M3 10l7-6 7 6M5 8.5V17h10V8.5",
  tree: "M10 17v-5M10 3l5.5 8h-11L10 3z",
  ruler: "M2.5 13.5l11-11 4 4-11 11zM5.5 10.5l1.5 1.5M8 8l1.5 1.5M10.5 5.5L12 7",
  eye: "M2 10s3-5.5 8-5.5 8 5.5 8 5.5-3 5.5-8 5.5S2 10 2 10zM10 12.5a2.5 2.5 0 1 0 0-5 2.5 2.5 0 0 0 0 5z",
  plan: "M3 3h14v14H3zM3 9h7M10 3v10M13 13v4",
  wand: "M3 17l9.5-9.5M11 3v2.5M15.5 4.5l-1.5 1.5M17 9h-2.5M13 6l1 1",
} as const;
export type IconName = keyof typeof PATHS;

export function Icon({ name, size = 16, className = "" }: { name: IconName; size?: number; className?: string }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 20 20"
      fill="none"
      stroke="currentColor"
      strokeWidth={1.5 * (20 / size)}
      strokeLinecap="square"
      strokeLinejoin="miter"
      className={`shrink-0 ${className}`}
      aria-hidden
    >
      {name === "info" && <circle cx="10" cy="10" r="7.5" />}
      {name === "question" && <circle cx="10" cy="10" r="7.5" />}
      <path d={PATHS[name]} />
    </svg>
  );
}

// Status reads through icon + text; colour only where a miss carries real risk (§2 utility colours).
export const STATUS_META: Record<
  Status,
  { label: string; icon: IconName; cls: string; hex: number; dashed?: boolean }
> = {
  fail: { label: "fail", icon: "x", cls: "text-danger", hex: 0xf5455c },
  unverifiable: { label: "can't verify", icon: "question", cls: "text-fg", hex: 0xc8c8cc, dashed: true },
  advisory: { label: "advisory", icon: "info", cls: "text-fg-2", hex: 0x9a9aa1 },
  pass: { label: "pass", icon: "check", cls: "text-success", hex: 0x3ed598 },
  not_applicable: { label: "not applicable", icon: "dash", cls: "text-fg-off", hex: 0x4a4a4e },
};
export const STATUS_ORDER: Status[] = ["fail", "unverifiable", "advisory", "pass", "not_applicable"];

export function StatusMark({ status, short = false }: { status: Status; short?: boolean }) {
  const m = STATUS_META[status];
  return (
    <span className={`inline-flex items-center gap-1.5 whitespace-nowrap text-xs ${m.cls}`}>
      <Icon name={m.icon} size={14} />
      {!short && m.label}
    </span>
  );
}

export function Chip({ children, predicted = false, title }: { children: ReactNode; predicted?: boolean; title?: string }) {
  return (
    <span className={predicted ? "chip-predicted" : "chip"} title={title}>
      {children}
    </span>
  );
}

// Where a fact came from. Model-inferred values are dashed and say so (§10).
const SOURCE_META: Record<Source, { label: string; title: string; predicted: boolean }> = {
  model: { label: "model", title: "Read from the BIM model", predicted: false },
  declared: { label: "declared", title: "Answered by you in the brief", predicted: false },
  inferred: { label: "inferred", title: "Guessed from names or geometry; confirm it in the brief", predicted: true },
  default: { label: "default", title: "A default value", predicted: true },
};

export function SourceBadge({ source }: { source: Source }) {
  const m = SOURCE_META[source];
  return (
    <Chip predicted={m.predicted} title={m.title}>
      {m.label}
    </Chip>
  );
}

// Headings end in a Corazon full stop, the suite's signature mark.
export function Title({ children, as: Tag = "h1", className = "display" }: { children: string; as?: "h1" | "h2" | "h3"; className?: string }) {
  const body = children.endsWith(".") ? children.slice(0, -1) : children;
  return (
    <Tag className={className}>
      {body}
      <span className="stop">.</span>
    </Tag>
  );
}

export function Spinner({ className = "h-4 w-4" }: { className?: string }) {
  return (
    <svg className={`animate-spin ${className}`} viewBox="0 0 24 24" fill="none" aria-hidden>
      <circle cx="12" cy="12" r="9" stroke="currentColor" strokeOpacity=".2" strokeWidth="2" />
      <path d="M21 12a9 9 0 0 0-9-9" stroke="currentColor" strokeWidth="2" />
    </svg>
  );
}

export function Skeleton({ rows = 4 }: { rows?: number }) {
  return (
    <div className="space-y-2 py-2" aria-busy>
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="h-10 animate-pulse rounded-sm bg-surface" />
      ))}
    </div>
  );
}

export const Loading = Skeleton;

// Inline, next to the control: one sentence.
export function FieldError({ error }: { error: unknown }) {
  const msg = error instanceof Error ? error.message : String(error);
  return <p className="mt-2 text-xs text-danger">{msg}</p>;
}

// System or model failure: a full panel with what failed and a way to retry (§10, §13).
export function ErrorBox({ error, title = "That didn't work", onRetry }: { error: unknown; title?: string; onRetry?: () => void }) {
  const msg = error instanceof Error ? error.message : String(error);
  return (
    <div className="panel flex items-start gap-3 border-line p-4">
      <Icon name="x" className="mt-0.5 text-danger" />
      <div className="min-w-0 flex-1">
        <p className="h2">{title}</p>
        <p className="mt-1 text-sm text-fg-2">{msg}</p>
      </div>
      {onRetry && (
        <button className="btn-secondary" onClick={onRetry}>
          <Icon name="refresh" /> retry
        </button>
      )}
    </div>
  );
}

export function fmt(v: unknown, digits = 2): string {
  if (v === null || v === undefined) return "—";
  if (typeof v === "number") return Number.isInteger(v) ? String(v) : v.toFixed(digits).replace(/\.?0+$/, "");
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "object") return JSON.stringify(v);
  return String(v);
}

export function humanPath(path: string): string {
  return path
    .replace(/^project\.overlays\./, "")
    .replace(/^project\./, "")
    .replace(/_m2\b/, " (m²)")
    .replace(/_m\b/, " (m)")
    .replace(/_/g, " ");
}
