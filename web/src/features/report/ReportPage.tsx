import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api } from "../../api/client";
import type { BuildingModel, Result, Status } from "../../api/types";
import { ErrorBox, Icon, STATUS_META, STATUS_ORDER, Skeleton, Spinner, StatusMark, Title } from "../../components/ui";
import Viewer from "../viewer/Viewer";
import ClauseRow from "./ClauseRow";
import FsiCard from "./FsiCard";

// Workbench layout (§12): results on the left, the 3D model on the right.

const RANK: Record<Status, number> = { fail: 0, unverifiable: 1, advisory: 2, pass: 3, not_applicable: 4 };
const KIND_LABEL: Record<string, string> = {
  spaces: "room",
  doors: "door",
  stairs: "staircase",
  units: "tenement",
  levels: "floor",
  areas: "FSI area",
  "site.edges": "plot side",
  site: "plot",
  building: "building",
};

interface Group {
  key: string;
  kind: string;
  name: string;
  detail: string;
  guid: string | null;
  results: Result[];
  worst: Status;
}

// Readable names for the elements a result refers to, from the model the report was run on.
function describe(model: BuildingModel | undefined, r: Result): { name: string; detail: string } {
  const el = r.element;
  if (!el || el.kind === "building") return { name: "whole building", detail: "" };
  if (el.kind === "site") return { name: "plot", detail: "" };
  const levels = new Map(model?.levels.map((l) => [l.id, l.name]) ?? []);
  if (el.kind === "site.edges") {
    const e = model?.site.edges.find((x) => x.id === el.id);
    const k = e?.kind.value;
    const w = e?.road_width_m.value;
    return { name: `side ${el.id}`, detail: k === "road" ? `road${w ? ` ${w} m` : ""}` : (k ?? "untagged").replace("_", " ") };
  }
  const coll = (model?.[el.kind as "spaces" | "doors" | "stairs" | "units" | "levels" | "areas"] ?? []) as {
    id: string;
    name?: string;
    level_id?: string;
    base_level_id?: string;
  }[];
  const item = coll.find((x) => x.id === el.id);
  const level = levels.get(item?.level_id ?? item?.base_level_id ?? "");
  if (el.kind === "doors" && model) {
    // Doors rarely have names: say which rooms they join instead.
    const d = model.doors.find((x) => x.id === el.id);
    const room = (id: string | null | undefined) => model.spaces.find((sp) => sp.id === id)?.name;
    const from = room(d?.from_space_id);
    if (from) {
      const to = d?.to_space_id ? room(d.to_space_id) : "outside";
      return { name: `door ${from} → ${to ?? "?"}`, detail: [el.id, level].filter(Boolean).join(" · ") };
    }
  }
  return { name: item?.name && item.name !== el.id ? item.name : `${KIND_LABEL[el.kind] ?? el.kind} ${el.id}`, detail: level ?? "" };
}

export default function ReportPage() {
  const { reportId = "" } = useParams();
  const navigate = useNavigate();
  const q = useQuery({ queryKey: ["report", reportId], queryFn: () => api.report(reportId) });
  const projectId = q.data?.project_id;
  const model = useQuery({ queryKey: ["model", projectId], queryFn: () => api.model(projectId!), enabled: !!projectId, retry: false });
  const [statuses, setStatuses] = useState<Set<Status>>(new Set(["fail", "unverifiable", "advisory", "pass"]));
  const [selected, setSelected] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [rerunning, setRerunning] = useState(false);
  const report = q.data;

  const statusByGuid = useMemo(() => {
    const m = new Map<string, Status>();
    for (const r of report?.results ?? []) {
      const g = r.element?.source_id;
      if (!g || r.status === "not_applicable") continue;
      const prev = m.get(g);
      if (!prev || RANK[r.status] < RANK[prev]) m.set(g, r.status);
    }
    return m;
  }, [report]);

  const groups = useMemo(() => {
    const byKey = new Map<string, Group>();
    for (const r of report?.results ?? []) {
      if (!statuses.has(r.status)) continue;
      const kind = r.element?.kind ?? "building";
      const key = `${kind}:${r.element?.id ?? ""}`;
      let g = byKey.get(key);
      if (!g) {
        g = { key, kind, ...describe(model.data?.model, r), guid: r.element?.source_id ?? null, results: [], worst: r.status };
        byKey.set(key, g);
      }
      g.results.push(r);
      if (RANK[r.status] < RANK[g.worst]) g.worst = r.status;
    }
    const out = [...byKey.values()];
    out.forEach((g) => g.results.sort((a, b) => RANK[a.status] - RANK[b.status]));
    const fails = (g: Group) => g.results.filter((r) => r.status === "fail").length;
    return out.sort((a, b) => RANK[a.worst] - RANK[b.worst] || fails(b) - fails(a) || a.name.localeCompare(b.name));
  }, [report, statuses, model.data]);

  if (q.isLoading) return <Skeleton rows={8} />;
  if (q.error || !report) return <ErrorBox error={q.error ?? "Report not found."} title="couldn't load the report" onRetry={() => void q.refetch()} />;

  async function rerun() {
    setRerunning(true);
    try {
      const { job_id } = await api.startCheck(report!.project_id);
      navigate(`/p/${report!.project_id}/jobs/${job_id}`);
    } catch {
      setRerunning(false);
    }
  }

  const s = report.summary;
  const toggleOpen = (key: string) =>
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  return (
    <div className="space-y-6">
      <header className="flex flex-wrap items-end justify-between gap-4 border-b border-line-subtle pb-5">
        <div>
          <p className="meta">{model.data?.model.project.name ?? "compliance report"}</p>
          <Title>{s.fail === 0 && s.unverifiable === 0 ? "no issues found." : `${s.fail} issue${s.fail === 1 ? "" : "s"} to fix.`}</Title>
          <p className="num mt-1 text-fg-2">
            {report.results.length - s.not_applicable} clauses checked · {new Date(String(report.created_at)).toLocaleString()}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <Link to={`/p/${report.project_id}/brief`} className="btn-secondary">
            <Icon name="edit" /> brief
          </Link>
          <button className="btn-secondary" onClick={() => void rerun()} disabled={rerunning}>
            {rerunning ? <Spinner /> : <Icon name="refresh" />} re-run
          </button>
          <a className="btn-secondary" href={api.bcfUrl(report.id)} title="One BCF topic per failure, for Solibri, BIMcollab, Archicad, BlenderBIM">
            <Icon name="download" /> BCF
          </a>
        </div>
      </header>

      <div className="flex flex-wrap gap-2" role="group" aria-label="Filter by status">
        {STATUS_ORDER.map((st) => {
          const on = statuses.has(st);
          return (
            <button
              key={st}
              aria-pressed={on}
              onClick={() =>
                setStatuses((prev) => {
                  const next = new Set(prev);
                  if (next.has(st)) next.delete(st);
                  else next.add(st);
                  return next;
                })
              }
              className={`flex h-8 items-center gap-2 rounded-sm border px-3 transition-colors ${
                on ? "border-line-strong bg-surface" : "border-line-subtle opacity-50 hover:opacity-80"
              }`}
            >
              <StatusMark status={st} short />
              <span className="num">{s[st]}</span>
              <span className="text-xs text-fg-2">{STATUS_META[st].label}</span>
            </button>
          );
        })}
      </div>

      {report.questions.length > 0 && (
        <Link
          to={`/p/${report.project_id}/brief`}
          className="panel flex items-center justify-between gap-4 border-dashed border-line px-4 py-3 transition-colors hover:border-line-strong"
        >
          <span className="flex items-center gap-3 text-sm">
            <Icon name="question" />
            <span>
              {s.unverifiable} clauses can't be checked: the model doesn't say {report.questions.length === 1 ? "one thing" : `${report.questions.length} things`} about the site.
            </span>
          </span>
          <span className="btn-primary shrink-0">answer</span>
        </Link>
      )}

      <div className="grid gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,0.85fr)]">
        <div className="space-y-4">
          {report.fsi && <FsiCard fsi={report.fsi} />}

          <div className="panel divide-y divide-line-subtle">
            {groups.map((g) => {
              const quiet = g.worst === "pass" || g.worst === "not_applicable";
              const open = !quiet || expanded.has(g.key);
              return (
                <section key={g.key} id={`el-${g.key}`} className={g.guid && g.guid === selected ? "bg-surface-raised" : ""}>
                  <button
                    className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-surface-raised"
                    onClick={() => {
                      if (g.guid) setSelected(g.guid);
                      if (quiet) toggleOpen(g.key);
                    }}
                    title={g.guid ? "Show in 3D" : undefined}
                  >
                    <span className="min-w-0 flex-1">
                      <span className="h2">{g.name}</span>
                      <span className="ml-2 text-xs text-fg-3">
                        {KIND_LABEL[g.kind] ?? g.kind}
                        {g.detail ? ` · ${g.detail}` : ""}
                      </span>
                    </span>
                    {quiet && (
                      <span className="flex items-center gap-1 text-xs text-fg-3">
                        {g.results.length} clause{g.results.length === 1 ? "" : "s"}
                        <Icon name="chevron" size={14} className={open ? "rotate-180" : ""} />
                      </span>
                    )}
                    <StatusMark status={g.worst} short />
                  </button>
                  {open && (
                    <ul className="divide-y divide-line-subtle border-t border-line-subtle">
                      {g.results.map((r) => (
                        <ClauseRow key={`${r.rule_id}:${r.element?.id ?? ""}`} r={r} />
                      ))}
                    </ul>
                  )}
                </section>
              );
            })}
            {groups.length === 0 && <p className="px-4 py-8 text-center text-sm text-fg-2">nothing matches these filters.</p>}
          </div>
        </div>

        <div className="xl:sticky xl:top-8 xl:h-[calc(100vh-4rem)]">
          <Viewer
            modelVersion={report.model_version}
            statusByGuid={statusByGuid}
            selectedGuid={selected}
            onPick={(guid) => {
              setSelected(guid);
              const g = groups.find((x) => x.guid === guid);
              if (g) document.getElementById(`el-${g.key}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
            }}
          />
        </div>
      </div>
    </div>
  );
}
