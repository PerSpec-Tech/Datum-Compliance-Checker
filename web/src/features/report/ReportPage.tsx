import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useParams } from "react-router-dom";
import { api, type DrawingFloor } from "../../api/client";
import type { BuildingModel, Result, Source, Status } from "../../api/types";
import { Chip, ErrorBox, Icon, Skeleton, SourceBadge, StatusMark, fmt } from "../../components/ui";
import { applyTheme, storedTheme } from "../../lib/theme";
import ElementThumb from "./ElementThumb";
import FsiCard from "./FsiCard";
import { KIND_LABEL, groupResults, type Group } from "./groups";

// P12.5: the report as a document (D30 compliance memo). Failures first, each with a plan
// thumbnail of the element; then what can't be verified yet; passes only on request. Prints to
// PDF in the light theme.

const ALL: Status[] = ["fail", "unverifiable", "advisory", "pass"];

export default function ReportPage() {
  const { reportId = "" } = useParams();
  const q = useQuery({ queryKey: ["report", reportId], queryFn: () => api.report(reportId) });
  const report = q.data;
  const projectId = report?.project_id;
  const model = useQuery({ queryKey: ["model", projectId], queryFn: () => api.model(projectId!), enabled: !!projectId, retry: false });
  const m = model.data?.model;
  const dxf = m?.meta.source_kind === "dxf";
  const drawing = useQuery({ queryKey: ["drawing", projectId], queryFn: () => api.drawing(projectId!), enabled: !!projectId && dxf, retry: false, staleTime: Infinity });
  const loc = m?.project.location.value;
  const place = useQuery({ queryKey: ["locate", loc?.lat, loc?.lon], queryFn: () => api.locate(loc!.lat, loc!.lon), enabled: !!loc, staleTime: Infinity });
  const [passes, setPasses] = useState(false);

  // Print in the light theme, whatever is on screen.
  useEffect(() => {
    const before = () => applyTheme("light");
    const after = () => applyTheme(storedTheme());
    window.addEventListener("beforeprint", before);
    window.addEventListener("afterprint", after);
    return () => {
      window.removeEventListener("beforeprint", before);
      window.removeEventListener("afterprint", after);
    };
  }, []);

  const groups = useMemo(() => groupResults(report?.results ?? [], m, new Set(ALL)), [report, m]);
  const fails = groups.filter((g) => g.results.some((r) => r.status === "fail"));
  const unsure = groups.filter((g) => g.worst === "unverifiable");
  const advisory = (report?.results ?? []).filter((r) => r.status === "advisory");
  const passed = groups.filter((g) => g.worst === "pass");

  if (q.isLoading) return <Skeleton rows={8} />;
  if (q.error || !report) return <ErrorBox error={q.error ?? "Report not found."} title="couldn't load the report" onRetry={() => void q.refetch()} />;
  const s = report.summary;
  const created = new Date(String(report.created_at));

  return (
    <div className="report-doc mx-auto max-w-[880px]">
      {/* Printed: the header and footer rows repeat on every page (Chrome repeats thead / tfoot). */}
      <table className="w-full border-collapse">
        <thead className="print-only">
          <tr>
            <td>
              <PrintBand name={m?.project.name ?? "compliance report"} date={created} top />
            </td>
          </tr>
        </thead>
        <tfoot className="print-only">
          <tr>
            <td>
              <PrintBand name={m?.project.name ?? "compliance report"} date={created} />
            </td>
          </tr>
        </tfoot>
        <tbody>
          <tr>
            <td className="p-0 align-top">
          <div className="no-print mb-6 flex flex-wrap items-center gap-2">
            <Link to={`/w/${report.project_id}`} className="btn-ghost">
              <Icon name="back" /> workspace
            </Link>
            <span className="flex-1" />
            <button className={`btn-secondary ${passes ? "border-fg text-fg" : ""}`} onClick={() => setPasses((v) => !v)} aria-pressed={passes}>
              <StatusMark status="pass" short /> {passes ? "hide passes" : "show passes"}
            </button>
            <a className="btn-secondary" href={api.bcfUrl(report.id)} title="One BCF topic per failure, for Solibri, BIMcollab, Archicad, BlenderBIM">
              <Icon name="download" /> BCF
            </a>
            <button className="btn-primary" onClick={() => window.print()}>
              <Icon name="download" /> save as PDF
            </button>
          </div>

          {/* ------------------------------------------------------------- header */}
          <header className="border-b border-line pb-6">
            <Brand className="no-print mb-4" />
        <p className="meta font-mono">compliance memo · {created.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}</p>
            <h1 className="display mt-2">
              {m?.project.name ?? "compliance report"}
              <span className="stop">.</span>
            </h1>
            <dl className="mt-4 grid gap-x-8 gap-y-1.5 text-sm sm:grid-cols-2">
              <Meta k="site">{place.data?.label ?? (loc ? `${loc.lat.toFixed(5)}, ${loc.lon.toFixed(5)}` : "not located")}</Meta>
              <Meta k="authority">Pune Municipal Corporation</Meta>
              <Meta k="rulebook">UDCPR 2020 → NBC 2016 · PMC TOD</Meta>
              <Meta k="model">{m ? `${m.project.name} (${m.meta.source_kind.toUpperCase()})` : "…"}</Meta>
            </dl>
            <div className="mt-5 flex flex-wrap gap-2">
              {ALL.map((st) => (
                <span key={st} className="flex h-8 items-center gap-2 rounded-sm border border-line-subtle px-3">
                  <StatusMark status={st} />
                  <span className="num">{s[st]}</span>
                </span>
              ))}
            </div>
            <p className="mt-4 text-xs text-fg-3">
              A design-time pre-check, not a permit. Every result quotes its clause; pass and fail are decided by the rule engine from the
              model and the facts below, never by the AI.
            </p>
          </header>

          {m && <Facts model={m} results={report.results} />}

          {report.fsi && (
            <section className="doc-entry mt-8">
              <FsiCard fsi={report.fsi} />
            </section>
          )}

          <Section title={fails.length ? `${s.fail} to fix, on ${fails.length} element${fails.length === 1 ? "" : "s"}` : "nothing to fix"}>
            {fails.length === 0 && <p className="text-sm text-fg-2">Every clause that applies and can be checked passes.</p>}
            {fails.map((g) => (
              <Entry key={g.key} g={g} model={m} floors={drawing.data?.floors} only={["fail"]} />
            ))}
          </Section>

          {unsure.length > 0 && (
            <Section title={`${unsure.length} can't be verified yet`}>
              {unsure.map((g) => (
                <Entry key={g.key} g={g} model={m} floors={drawing.data?.floors} only={["unverifiable"]} compact />
              ))}
            </Section>
          )}

          {advisory.length > 0 && (
            <Section title="advisory">
              <ul className="divide-y divide-line-subtle border-y border-line-subtle">
                {advisory.map((r) => (
                  <Line key={`${r.rule_id}:${r.element?.id ?? ""}`} r={r} />
                ))}
              </ul>
            </Section>
          )}

          {passes && (
            <Section title={`${s.pass} pass`}>
              <ul className="divide-y divide-line-subtle border-y border-line-subtle">
                {passed.map((g) => (
                  <li key={g.key} className="flex items-baseline gap-3 py-2 text-sm">
                    <StatusMark status="pass" short />
                    <span className="min-w-0 flex-1">
                      {g.name}{" "}
                      <span className="text-xs text-fg-3">
                        {KIND_LABEL[g.kind] ?? g.kind}
                        {g.detail ? ` · ${g.detail}` : ""}
                      </span>
                    </span>
                    <span className="font-mono text-2xs text-fg-3">
                      {g.results
                        .map((r) => r.clause.ref)
                        .filter((v, i, a) => a.indexOf(v) === i)
                        .join(" · ")}
                    </span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          <footer className="mt-12 border-t border-line-subtle pt-4 font-mono text-2xs text-fg-3">
            report {report.id} · model {report.model_version} · rules {report.ruleset_version} · {created.toLocaleString()}
          </footer>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  );
}

function Meta({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex gap-3">
      <dt className="w-20 shrink-0 text-fg-3">{k}</dt>
      <dd className="min-w-0">{children}</dd>
    </div>
  );
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-10">
      <h2 className="h2 mb-4 border-b border-line-subtle pb-2">{title}</h2>
      <div className="space-y-6">{children}</div>
    </section>
  );
}

// The planning facts every result depends on, with where each came from.
function Facts({ model, results }: { model: BuildingModel; results: Result[] }) {
  // What the check used (site lookups and suggestions are applied during the check, so the
  // stored model may not have them); the model for anything no rule looked at.
  const used = new Map(results.flatMap((r) => r.facts_used).map((f) => [f.path, f]));
  const p = structuredClone(model.project);
  for (const k of ["occupancy", "building_type", "zone", "congested_area"] as const) {
    const f = used.get(`project.${k}`);
    if (f) (p[k] as { value: unknown; source: Source }) = { value: f.value, source: f.source };
  }
  for (const k of ["metro_tod", "nearest_metro_station"] as const) {
    const f = used.get(`project.overlays.${k}`);
    if (f) (p.overlays[k] as { value: unknown; source: Source }) = { value: f.value, source: f.source };
  }
  const occ = p.occupancy.value;
  const station = p.overlays.nearest_metro_station.value;
  const roads = model.site.edges.filter((e) => e.kind.value === "road");
  const yes = (v: boolean | null | undefined) => (v == null ? "—" : v ? "yes" : "no");
  const rows: [string, string, Source | null][] = [
    ["occupancy", occ ? (occ.subdivision ?? occ.group) : "—", p.occupancy.source],
    ["building type", p.building_type.value?.replace(/_/g, " ") ?? "—", p.building_type.source],
    ["land use / zone", p.zone.value ?? "—", p.zone.source],
    ["congested area", yes(p.congested_area.value), p.congested_area.source],
    ["metro TOD zone", yes(p.overlays.metro_tod.value), p.overlays.metro_tod.source],
    ["nearest station", station ? `${station.name}, ${Math.round(station.distance_m)} m` : "—", p.overlays.nearest_metro_station.source],
    ["road", roads.length ? roads.map((e) => `${e.id} ${e.road_width_m.value ?? "?"} m`).join(" · ") : "—", roads[0]?.road_width_m.source ?? null],
  ];
  return (
    <section className="doc-entry mt-8">
      <h2 className="h2 mb-3">planning facts</h2>
      <table className="w-full text-sm">
        <tbody>
          {rows.map(([k, v, src]) => (
            <tr key={k} className="border-t border-line-subtle">
              <td className="w-40 py-1.5 text-fg-2">{k}</td>
              <td className="py-1.5">{v}</td>
              <td className="py-1.5 text-right">{src && v !== "—" ? <SourceBadge source={src} /> : null}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
}

function Entry({
  g,
  model,
  floors,
  only,
  compact = false,
}: {
  g: Group;
  model?: BuildingModel;
  floors?: DrawingFloor[];
  only: Status[];
  compact?: boolean;
}) {
  const rs = g.results.filter((r) => only.includes(r.status));
  const missing = [...new Set(rs.flatMap((r) => r.missing_inputs))];
  return (
    <article className="doc-entry flex flex-col gap-4 sm:flex-row">
      {model && !compact && <ElementThumb model={model} group={g} floors={floors} />}
      <div className="min-w-0 flex-1">
        <p>
          <span className="h2">{g.name}</span>
          <span className="ml-2 text-xs text-fg-3">
            {KIND_LABEL[g.kind] ?? g.kind}
            {g.detail ? ` · ${g.detail}` : ""}
          </span>
        </p>
        <ul className="mt-2 divide-y divide-line-subtle border-y border-line-subtle">
          {rs.map((r) => (
            <Line key={r.rule_id} r={r} excerpt={!compact} />
          ))}
        </ul>
        {compact && missing.length > 0 && (
          <p className="mt-2 text-xs text-fg-2">
            needs: <span className="font-mono">{missing.join(", ")}</span>
          </p>
        )}
      </div>
    </article>
  );
}

function Line({ r, excerpt = false }: { r: Result; excerpt?: boolean }) {
  const shown = (r.measured !== null || r.limit !== null) && r.status !== "not_applicable";
  return (
    <li className="py-2.5">
      <div className="flex items-start gap-3">
        <span className="pt-0.5">
          <StatusMark status={r.status} short />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-sm">{r.title}</p>
          <p className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-fg-3">
            <span className="font-mono">{r.clause.ref}</span> · {r.clause.source}
            {r.rule_status === "draft" && <Chip predicted>draft</Chip>}
          </p>
        </div>
        {shown && (
          <div className="shrink-0 text-right">
            <p className="num text-sm">
              {fmt(r.measured)}
              <span className="text-fg-3"> / {fmt(r.limit)}</span>
            </p>
            {r.fix_by && (
              <p className={`font-mono text-2xs ${r.status === "fail" ? "text-danger" : "text-fg-2"}`}>
                {r.fix_by.direction === "increase" ? "+" : "−"}
                {fmt(r.fix_by.amount)}
                {r.fix_by.unit ? ` ${r.fix_by.unit}` : ""}
              </p>
            )}
          </div>
        )}
      </div>
      {excerpt && (
        <div className="ml-7 mt-2 space-y-1.5 text-xs">
          <p className="text-fg-2">{r.message}</p>
          <blockquote className="border-l border-fg-2 pl-3 text-fg">“{r.clause.excerpt}”</blockquote>
        </div>
      )}
    </li>
  );
}

// PerSpec's mark and wordmark (web/public/brand). Black artwork: inverted in the dark theme.
function Brand({ className = "", size = 28 }: { className?: string; size?: number }) {
  return (
    <span className={`flex items-center gap-2.5 ${className}`} aria-label="PerSpec">
      <img src="/brand/perspec-mark.png" alt="" style={{ height: size }} className="brand-art" />
      <img src="/brand/perspec-wordmark.png" alt="PERSPEC" style={{ height: size * 0.32 }} className="brand-art" />
    </span>
  );
}

function PrintBand({ name, date, top = false }: { name: string; date: Date; top?: boolean }) {
  return top ? (
    <div className="mb-6 flex items-end justify-between border-b border-line pb-3">
      <Brand size={30} />
      <span className="text-right font-mono text-2xs text-fg-3">
        {name} · compliance memo · {date.toLocaleDateString(undefined, { day: "numeric", month: "short", year: "numeric" })}
      </span>
    </div>
  ) : (
    <div className="mt-6 flex items-center justify-between border-t border-line-subtle pt-2 font-mono text-2xs text-fg-3">
      <span>PerSpec compliance checker · a design-time pre-check, not a permit</span>
      <span>UDCPR 2020 → NBC 2016 · PMC</span>
    </div>
  );
}
