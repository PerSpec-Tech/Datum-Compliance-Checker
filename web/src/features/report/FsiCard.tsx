import type { FsiSummary } from "../../api/types";
import { Icon, fmt, humanPath } from "../../components/ui";

// FSI headroom (D30). The used FSI is the lead data series (Corazon); limits are hairline ticks.
export default function FsiCard({ fsi }: { fsi: FsiSummary }) {
  const top = Math.max(fsi.max_permissible ?? 0, fsi.base_permissible ?? 0, fsi.used ?? 0) * 1.1 || 1;
  const at = (v: number | null) => `${Math.min(100, ((v ?? 0) / top) * 100)}%`;
  const over = fsi.used !== null && fsi.max_permissible !== null && fsi.used > fsi.max_permissible;

  return (
    <section className="panel p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 className="h1">FSI headroom</h2>
        {fsi.plot_area_m2 !== null && (
          <p className="num text-fg-2">
            plot {fmt(fsi.plot_area_m2, 1)} m² · built-up {fmt(fsi.built_up_m2, 1)} m²
          </p>
        )}
      </div>

      {fsi.used === null ? (
        <p className="mt-3 flex gap-2 text-sm text-fg-2">
          <Icon name="question" className="mt-0.5" />
          FSI can't be worked out yet. Missing: {fsi.missing_inputs.map(humanPath).join(", ") || "plot and built-up area"}.
        </p>
      ) : (
        <>
          <div className="mt-5 grid grid-cols-3 gap-4">
            <Stat label="used" value={fmt(fsi.used, 2)} />
            <Stat label="base permissible" value={fmt(fsi.base_permissible, 2)} />
            <Stat label="maximum (premium / TOD)" value={fmt(fsi.max_permissible, 2)} />
          </div>
          <div className="relative mt-5 h-6" aria-hidden>
            <div className="absolute inset-x-0 top-3 h-px bg-line" />
            <div className="absolute left-0 top-[11px] h-[3px] bg-accent" style={{ width: at(fsi.used) }} />
            {fsi.base_permissible !== null && <Tick at={at(fsi.base_permissible)} label="base" />}
            {fsi.max_permissible !== null && <Tick at={at(fsi.max_permissible)} label="max" />}
          </div>
          <div className="mt-4 grid gap-2 sm:grid-cols-2">
            <Headroom label="within base FSI" value={fsi.headroom_base_m2} />
            <Headroom label="within maximum FSI" value={fsi.headroom_max_m2} strong={over} />
          </div>
        </>
      )}
      {fsi.basis.length > 0 && (
        <ul className="mt-4 space-y-0.5 text-xs text-fg-3">
          {fsi.basis.map((b) => (
            <li key={b}>{b}</li>
          ))}
        </ul>
      )}
    </section>
  );
}

function Tick({ at, label }: { at: string; label: string }) {
  return (
    <div className="absolute top-0 h-6" style={{ left: at }}>
      <div className="h-6 w-px bg-fg-2" />
      <span className="absolute left-1 top-0 font-mono text-2xs text-fg-2">{label}</span>
    </div>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="font-mono text-[22px] font-medium leading-7 tabular-nums">{value}</p>
      <p className="meta mt-0.5">{label}</p>
    </div>
  );
}

function Headroom({ label, value, strong }: { label: string; value: number | null; strong?: boolean }) {
  const over = value !== null && value < 0;
  return (
    <div className="flex items-baseline justify-between rounded-sm border border-line-subtle px-3 py-2 text-sm">
      <span className="text-fg-2">{label}</span>
      <span className={`num ${over && strong ? "text-danger" : ""}`}>
        {value === null ? "—" : over ? `${fmt(-value, 1)} m² over` : `${fmt(value, 1)} m² left`}
      </span>
    </div>
  );
}
