import { useEffect, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { BuildingModel, CheckReport, Question } from "../../api/types";
import { ErrorBox, Icon, Loading, Spinner, Title } from "../../components/ui";
import EdgePlan, { type EdgeTag } from "./EdgePlan";
import MapPin from "./MapPin";

export const OCCUPANCY: Record<string, string> = {
  A: "A · Residential",
  B: "B · Educational",
  C: "C · Institutional",
  D: "D · Assembly",
  E: "E · Business",
  F: "F · Mercantile",
  G: "G · Industrial",
  H: "H · Storage",
  J: "J · Hazardous",
};
export const RESIDENTIAL_SUB: Record<string, string> = {
  "A-1": "A-1 Lodging or rooming houses",
  "A-2": "A-2 One or two-family private dwellings",
  "A-3": "A-3 Dormitories",
  "A-4": "A-4 Apartment houses",
  "A-5": "A-5 Hotels",
  "A-6": "A-6 Hotels (starred)",
};
const LABEL: Record<string, string> = {
  group_housing: "Group housing",
  standalone: "Standalone building",
  bungalow_self_use: "Bungalow (self use)",
  mixed_use: "Mixed use",
  other: "Other",
};

// Read a value from the merged model by an engine path such as `project.overlays.metro_tod`
// or `spaces[S4].usage`. Facts return their `.value`.
export function getPath(model: BuildingModel, path: string): unknown {
  let node: unknown = model;
  for (const part of path.split(".")) {
    const m = /^([A-Za-z_]\w*)(?:\[([^\]]+)\])?$/.exec(part);
    if (!m || typeof node !== "object" || node === null) return undefined;
    node = (node as Record<string, unknown>)[m[1]];
    if (m[2] !== undefined) node = (node as { id: string }[] | undefined)?.find((e) => e.id === m[2]);
  }
  if (node && typeof node === "object" && "source" in node && "value" in node) return (node as { value: unknown }).value;
  return node;
}

// `spaces[*].usage` → the concrete element paths the last report was missing.
export function concretePaths(q: Question, report: CheckReport): string[] {
  const re = new RegExp("^" + q.path.replace(/[.]/g, "\\.").replace("[*]", "\\[([^\\]]+)\\]") + "$");
  const set = new Set<string>();
  for (const r of report.results) for (const p of r.missing_inputs) if (re.test(p)) set.add(p);
  return [...set].sort();
}

export default function BriefPage() {
  const { projectId = "" } = useParams();
  const navigate = useNavigate();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.project(projectId) });
  const model = useQuery({ queryKey: ["model", projectId], queryFn: () => api.model(projectId), retry: false });
  const reportId = project.data?.latest_report_id;
  const report = useQuery({
    queryKey: ["report", reportId],
    queryFn: () => api.report(reportId!),
    enabled: !!reportId,
  });

  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const [edgeTags, setEdgeTags] = useState<Record<string, EdgeTag>>({});
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<unknown>(null);

  // Start from what the model (with earlier answers merged in) already says.
  useEffect(() => {
    const m = model.data?.model;
    if (!m) return;
    const tags: Record<string, EdgeTag> = {};
    for (const e of m.site.edges)
      tags[e.id] = { kind: e.kind.value, road_width_m: e.road_width_m.value, road_width_basis: e.road_width_basis.value };
    setEdgeTags(tags);
  }, [model.data]);

  const questions = useMemo(
    () => [...(report.data?.questions ?? [])].sort((a, b) => b.unlocks - a.unlocks),
    [report.data],
  );

  if (project.isLoading || model.isLoading || report.isLoading) return <Loading />;
  if (project.error) return <ErrorBox error={project.error} title="couldn't load the project" />;
  if (model.error) return <ErrorBox error={model.error} title="couldn't load the model" />;
  const m = model.data!.model;
  const current = (path: string) => (path in answers ? answers[path] : getPath(m, path));
  const set = (path: string, v: unknown) => setAnswers((a) => ({ ...a, [path]: v }));

  async function save(run: boolean) {
    setSaving(true);
    setError(null);
    try {
      const payload: Record<string, unknown> = {};
      for (const [k, v] of Object.entries(answers)) if (v !== undefined && v !== "") payload[k] = v;
      const edges = Object.fromEntries(
        Object.entries(edgeTags)
          .map(([id, t]) => [id, Object.fromEntries(Object.entries(t).filter(([, v]) => v !== null && v !== undefined))])
          .filter(([, t]) => Object.keys(t as object).length > 0),
      );
      if (Object.keys(edges).length) payload["site.edges"] = edges;
      await api.patchBrief(projectId, payload);
      if (run) {
        const { job_id } = await api.startCheck(projectId);
        navigate(`/w/${projectId}?job=${job_id}`);
      } else {
        setSaving(false);
      }
    } catch (e) {
      setError(e);
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-[760px] space-y-6">
      <div>
        <p className="meta">{project.data?.name}</p>
        <Title>project brief.</Title>

      </div>

      {!report.data && (
        <div className="panel px-4 py-3 text-sm text-fg-2">
          Run a first check to see which facts are missing.
        </div>
      )}
      {model.data!.skipped_answers.length > 0 && (
        <div className="panel border-dashed border-line px-4 py-3 text-sm text-fg-2">
          Some earlier answers no longer match the model (an edge or room changed): {model.data!.skipped_answers.join(", ")}
        </div>
      )}

      {questions.map((q, i) => (
        <section key={q.path} className="panel p-5">
          <div className="mb-3 flex items-start justify-between gap-4">
            <h2 className="h2">
              <span className="mr-3 font-mono text-fg-3">{String(i + 1).padStart(2, "0")}</span>
              {q.prompt}
            </h2>
            {q.unlocks > 0 && (
              <span className="chip shrink-0">
                unlocks {q.unlocks} check{q.unlocks === 1 ? "" : "s"}
              </span>
            )}
          </div>
          <QuestionInput
            q={q}
            model={m}
            report={report.data!}
            current={current}
            set={set}
            edgeTags={edgeTags}
            setEdgeTags={setEdgeTags}
          />
        </section>
      ))}

      {error ? <ErrorBox error={error} title="couldn't save the answers" /> : null}

      <div className="sticky bottom-4 flex flex-wrap items-center justify-end gap-2 rounded-md border border-line bg-surface p-3">
        {reportId && (
          <Link to={`/reports/${reportId}`} className="btn-ghost mr-auto">
            <Icon name="back" />
            last report
          </Link>
        )}
        <button className="btn-secondary" disabled={saving} onClick={() => void save(false)}>
          <Icon name="check" /> save
        </button>
        <button className="btn-primary" disabled={saving} onClick={() => void save(true)}>
          {saving ? <Spinner /> : <Icon name="refresh" />} save and re-check
        </button>
      </div>
    </div>
  );
}

function QuestionInput({
  q,
  model,
  report,
  current,
  set,
  edgeTags,
  setEdgeTags,
}: {
  q: Question;
  model: BuildingModel;
  report: CheckReport;
  current: (path: string) => unknown;
  set: (path: string, v: unknown) => void;
  edgeTags: Record<string, EdgeTag>;
  setEdgeTags: (t: Record<string, EdgeTag>) => void;
}) {
  if (q.input_type === "edge_tags")
    return <EdgePlan edges={model.site.edges} footprint={model.building.footprint} tags={edgeTags} onChange={setEdgeTags} />;

  if (q.input_type === "latlon")
    return (
      <MapPin
        value={(current(q.path) as { lat: number; lon: number } | null) ?? null}
        onChange={(v) => set(q.path, v)}
      />
    );

  if (q.path === "site.boundary")
    return <p className="text-sm text-fg-2">This has to be fixed in the model itself; re-upload once it's added.</p>;

  if (q.path.includes("[*]")) {
    const paths = concretePaths(q, report);
    return (
      <div className="divide-y divide-line-subtle">
        {paths.map((p) => {
          const id = /\[([^\]]+)\]/.exec(p)?.[1] ?? p;
          const coll = p.split("[")[0] as "spaces" | "areas" | "units";
          const item = (model[coll] as { id: string; name: string }[]).find((e) => e.id === id);
          return (
            <div key={p} className="flex items-center justify-between gap-4 py-2">
              <span className="text-sm">
                {item?.name ?? id} <span className="font-mono text-2xs text-fg-3">{id}</span>
              </span>
              <div className="w-48">
                <Scalar type={q.input_type} options={q.options} value={current(p)} onChange={(v) => set(p, v)} />
              </div>
            </div>
          );
        })}
      </div>
    );
  }

  if (q.path === "project.occupancy") {
    const v = (current(q.path) as { group: string; subdivision: string | null } | null) ?? null;
    return (
      <div className="grid gap-3 sm:grid-cols-2">
        <select
          className="input"
          value={v?.group ?? ""}
          onChange={(e) => set(q.path, e.target.value ? { group: e.target.value, subdivision: null } : null)}
        >
          <option value="">Choose a group…</option>
          {(q.options ?? Object.keys(OCCUPANCY)).map((o) => (
            <option key={o} value={o}>
              {OCCUPANCY[o] ?? o}
            </option>
          ))}
        </select>
        {v?.group === "A" && (
          <select
            className="input"
            value={v.subdivision ?? ""}
            onChange={(e) => set(q.path, { group: "A", subdivision: e.target.value || null })}
          >
            <option value="">Subdivision…</option>
            {Object.entries(RESIDENTIAL_SUB).map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
        )}
      </div>
    );
  }

  return (
    <div className="max-w-sm">
      <Scalar type={q.input_type} options={q.options} value={current(q.path)} onChange={(v) => set(q.path, v)} />
    </div>
  );
}

export function Scalar({
  type,
  options,
  value,
  onChange,
}: {
  type: Question["input_type"];
  options: string[] | null;
  value: unknown;
  onChange: (v: unknown) => void;
}) {
  if (type === "bool")
    return (
      <div className="flex gap-1.5">
        {[true, false].map((b) => (
          <button
            key={String(b)}
            type="button"
            onClick={() => onChange(b)}
            className={`h-9 rounded-sm border px-4 text-sm transition-colors ${value === b ? "border-fg bg-surface-raised text-fg" : "border-line text-fg-2 hover:border-line-strong hover:text-fg"}`}
          >
            <span className="flex items-center gap-1.5">
              <Icon name={b ? "check" : "x"} size={14} /> {b ? "Yes" : "No"}
            </span>
          </button>
        ))}
      </div>
    );
  if (type === "enum" && options)
    return (
      <select className="input" value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value || undefined)}>
        <option value="">Choose…</option>
        {options.map((o) => (
          <option key={o} value={o}>
            {LABEL[o] ?? o.replace(/_/g, " ")}
          </option>
        ))}
      </select>
    );
  if (type === "number")
    return (
      <input
        className="input"
        type="number"
        step="any"
        value={value === null || value === undefined ? "" : String(value)}
        onChange={(e) => onChange(e.target.value === "" ? undefined : Number(e.target.value))}
      />
    );
  return <input className="input" value={(value as string) ?? ""} onChange={(e) => onChange(e.target.value)} />;
}
