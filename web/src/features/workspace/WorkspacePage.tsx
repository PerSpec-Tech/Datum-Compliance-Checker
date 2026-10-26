import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, type JobEvent } from "../../api/client";
import type { Status } from "../../api/types";
import { ErrorBox, Icon, STATUS_META, Spinner, StatusMark } from "../../components/ui";
import ThemeToggle from "../../components/ThemeToggle";
import { rememberProject } from "../../lib/recent";
import { bunchGroups, groupResults, isBunch, worstBy, type Group } from "../report/groups";
import PlanViewer from "../viewer/PlanViewer";
import { gapTo } from "../viewer/SetbackLayer";
import Viewer from "../viewer/Viewer";
import IssueCard from "./IssueCard";
import SiteWizard from "../site/SiteWizard";

// P12.4: one full-screen workspace, like Revit or AutoCAD. The drawing is the screen; the top bar
// holds the view and the filters; failures show first, passes only on request; clicking an element
// opens a small card at it; answers and site changes re-run the check in place.

type Job = { id: string; pct: number; msg: string | null; error: string | null };
type Card = { key: string; x: number | null; y: number | null };

export default function WorkspacePage() {
  const { projectId = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const qc = useQueryClient();
  const project = useQuery({ queryKey: ["project", projectId], queryFn: () => api.project(projectId) });
  const reportId = project.data?.latest_report_id ?? null;
  const report = useQuery({ queryKey: ["report", reportId], queryFn: () => api.report(reportId!), enabled: !!reportId });
  const model = useQuery({ queryKey: ["model", projectId], queryFn: () => api.model(projectId), retry: false });
  const pack = useQuery({ queryKey: ["live-pack", projectId], queryFn: () => api.livePack(projectId), retry: false, enabled: !!reportId });

  const [show, setShow] = useState<Set<Status>>(new Set(["fail", "unverifiable"]));
  const [mode, setMode] = useState<"2d" | "3d" | null>(null);
  const [list, setList] = useState(true);
  // ?el=<kind>:<id> opens that element's card (links from the report).
  const [card, setCard] = useState<Card | null>(() => (params.get("el") ? { key: params.get("el")!, x: null, y: null } : null));
  const [site, setSite] = useState(params.get("site") === "1");
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const pointer = useRef<{ x: number; y: number } | null>(null);
  const canvas = useRef<HTMLDivElement>(null);

  const m = model.data?.model;
  const r = report.data;
  const dxf = m?.meta.source_kind === "dxf";
  const view = dxf ? "2d" : (mode ?? "3d");
  const results = useMemo(() => r?.results ?? [], [r]);
  const counts = r?.summary;
  const groups = useMemo(() => groupResults(results, m, show), [results, m, show]);
  const issues = useMemo(() => groupResults(results, m, new Set<Status>(["fail", "unverifiable"])), [results, m]);
  const byId = useMemo(() => worstBy(results, (x) => x.element?.id, show), [results, show]);
  const byGuid = useMemo(() => worstBy(results, (x) => x.element?.source_id, show), [results, show]);
  const open = card ? groups.find((g) => g.key === card.key) ?? issues.find((g) => g.key === card.key) : undefined;
  const needsSite = !!m && (!m.project.location.value || !m.site.boundary || m.site.edges.some((e) => !e.kind.value));

  // A project that hasn't been checked yet opens on the site setup, 2D or 3D. What the file
  // already says is filled in there, so a complete model is one click from its check.
  const asked = useRef(false);
  useEffect(() => {
    if (asked.current || !m || !project.data || reportId || params.get("job")) return;
    asked.current = true;
    setSite(true);
  }, [m, project.data, reportId, params]);

  useEffect(() => {
    if (project.data) rememberProject({ id: projectId, name: project.data.name, reportId: reportId ?? undefined });
  }, [project.data, projectId, reportId]);

  // A check started elsewhere (the new-check page) arrives as ?job=…
  useEffect(() => {
    const id = params.get("job");
    if (id && job?.id !== id) setJob({ id, pct: 0, msg: null, error: null });
  }, [params]); // eslint-disable-line react-hooks/exhaustive-deps

  // Follow the running check in the status bar; refresh everything when it's done.
  useEffect(() => {
    if (!job || job.error) return;
    const es = new EventSource(api.eventsUrl(job.id));
    es.onmessage = (msg) => {
      const e = JSON.parse(msg.data) as JobEvent;
      if (e.stage === "done") {
        es.close();
        setJob(null);
        setParams((p) => { p.delete("job"); return p; }, { replace: true }); // prettier-ignore
        void qc.invalidateQueries({ queryKey: ["project", projectId] });
        void qc.invalidateQueries({ queryKey: ["model", projectId] });
        void qc.invalidateQueries({ queryKey: ["live-pack", projectId] });
      } else if (e.stage === "error") {
        es.close();
        setJob((j) => (j ? { ...j, error: e.error ?? e.msg ?? "The check failed." } : j));
      } else setJob((j) => (j ? { ...j, pct: e.pct ?? j.pct, msg: e.msg ?? j.msg } : j));
    };
    es.onerror = () => {
      es.close();
      setJob((j) => (j ? { ...j, error: j.error ?? "Lost the connection to the server." } : j));
    };
    return () => es.close();
  }, [job?.id]); // eslint-disable-line react-hooks/exhaustive-deps

  // Save the site without checking: the project keeps it; the check can run later.
  async function saveSite(answers: Record<string, unknown>) {
    if (Object.keys(answers).length) await api.patchBrief(projectId, answers);
    await qc.invalidateQueries({ queryKey: ["project", projectId] });
    await qc.invalidateQueries({ queryKey: ["model", projectId] });
  }

  async function check(answers?: Record<string, unknown>) {
    setBusy(true);
    setError(null);
    try {
      if (answers && Object.keys(answers).length) await api.patchBrief(projectId, answers);
      const { job_id } = await api.startCheck(projectId);
      setJob({ id: job_id, pct: 0, msg: null, error: null });
      setSite(false);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }

  function pick(key: string) {
    const p = pointer.current, c = canvas.current?.getBoundingClientRect();
    setCard({ key, x: p && c ? p.x - c.left : null, y: p && c ? p.y - c.top : null });
  }

  const toggle = (s: Status) =>
    setShow((prev) => {
      const next = new Set(prev);
      if (next.has(s)) next.delete(s);
      else next.add(s);
      return next;
    });

  if (project.error) return <Shell><div className="m-auto max-w-md p-6"><ErrorBox error={project.error} title="couldn't open the project" /></div></Shell>;

  const fsi = r?.fsi;
  const fsiOver = fsi && fsi.max_permissible != null && fsi.used != null && fsi.used > fsi.max_permissible;
  // Margins are only "clear" when every side has one to measure against (untagged sides have none).
  const known = pack.data?.edges.filter((e) => e.margin_m != null) ?? [];
  const short = pack.data && m?.building.footprint && known.length > 0 && known.length === pack.data.edges.length
    ? known.filter((e) => gapTo(e.a, e.b, m.building.footprint!) + 0.005 < e.margin_m!).length
    : null;

  return (
    <Shell>
      {/* ------------------------------------------------------------- top bar */}
      <header className="flex h-12 shrink-0 items-center gap-2 border-b border-line-subtle bg-canvas px-3">
        <Link to="/projects" className="flex items-center gap-2 pr-2 text-fg" title="Projects">
          <svg width="18" height="18" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
            <path d="M3 4h9M3 8h6M3 12h4" />
            <path d="M10 13l2.5 2.5L17 10" />
          </svg>
        </Link>
        <ProjectName
          id={projectId}
          name={project.data?.name ?? m?.project.name ?? "…"}
          onRenamed={() => void qc.invalidateQueries({ queryKey: ["project", projectId] })}
        />
        <Sep />
        {!dxf && m && (
          <Seg>
            {(["2d", "3d"] as const).map((v) => (
              <SegBtn key={v} on={view === v} onClick={() => setMode(v)}>
                <Icon name={v === "2d" ? "plan" : "cube"} size={14} />
                {v.toUpperCase()}
              </SegBtn>
            ))}
          </Seg>
        )}
        {counts && (
          <Seg>
            {(["fail", "unverifiable", "pass"] as Status[]).map((s) => (
              <SegBtn key={s} on={show.has(s)} onClick={() => toggle(s)} title={s === "pass" ? "Show what passes, in green" : `Show ${STATUS_META[s].label}`}>
                <StatusMark status={s} short />
                <span className="num">{counts[s]}</span>
                {s === "pass" && <span className="hidden text-fg-2 md:inline">show passes</span>}
              </SegBtn>
            ))}
          </Seg>
        )}
        <button className={`btn-ghost h-8 px-2 text-xs ${list ? "text-fg" : "text-fg-2"}`} onClick={() => setList((v) => !v)} aria-pressed={list}>
          <Icon name="list" size={14} /> issues
        </button>
        <div className="ml-auto flex items-center gap-2">
          {m && (
            <button className={needsSite ? "btn-primary h-8" : "btn-secondary h-8"} onClick={() => setSite(true)} title="Place the drawing on the map, draw the plot, tag the roads">
              <Icon name="pin" /> {needsSite ? "set the site" : "site"}
            </button>
          )}
          <button className="btn-secondary h-8" onClick={() => void check()} disabled={!!job && !job.error} title="Run the check again">
            <Icon name="refresh" />
          </button>
          {r && (
            <Link to={`/reports/${r.id}`} className="btn-secondary h-8">
              <Icon name="book" /> report
            </Link>
          )}
          <ThemeToggle />
        </div>
      </header>

      {/* ------------------------------------------------------------- canvas */}
      <div
        ref={canvas}
        className="relative min-h-0 flex-1"
        onPointerDownCapture={(e) => (pointer.current = { x: e.clientX, y: e.clientY })}
      >
        {m && view === "2d" && (
          <PlanViewer
            model={m}
            projectId={projectId}
            statusById={byId}
            selectedId={open?.id ?? null}
            onPick={(kind, id) => pick(`${kind}:${id}`)}
          />
        )}
        {m && view === "3d" && model.data && (
          <Viewer
            modelVersion={model.data.model_version}
            projectId={projectId}
            statusByGuid={byGuid}
            selectedGuid={open?.guid ?? null}
            onPick={(guid) => {
              const g = groups.find((x) => x.guid === guid) ?? issues.find((x) => x.guid === guid);
              if (g) pick(g.key);
            }}
          />
        )}
        {model.isLoading && (
          <div className="absolute inset-0 grid place-items-center text-sm text-fg-2">
            <Spinner />
          </div>
        )}

        {list && r && (
          <IssueList
            groups={issues}
            selected={open?.key}
            allClear={counts?.fail === 0 && counts?.unverifiable === 0}
            onPick={(g) => setCard({ key: g.key, x: null, y: null })}
          />
        )}

        {open && r && (
          <div className="pointer-events-none absolute inset-3 z-[600]">
            <div className="pointer-events-auto absolute w-[min(380px,100%)]" style={place(card!, canvas.current, view === "2d" ? 44 : 0)}>
              <IssueCard
                key={open.key}
                group={open}
                report={r}
                model={m}
                busy={busy || (!!job && !job.error)}
                onClose={() => setCard(null)}
                onAnswer={(a) => void check(a)}
                onSetSite={() => setSite(true)}
              />
            </div>
          </div>
        )}
      </div>

      {/* ------------------------------------------------------------- status bar */}
      <footer className="flex h-8 shrink-0 items-center gap-4 overflow-x-auto border-t border-line-subtle bg-canvas px-3 font-mono text-2xs text-fg-2">
        {job ? (
          job.error ? (
            <span className="flex items-center gap-2 text-danger">
              <Icon name="x" size={12} /> {job.error}
              <button className="flex items-center gap-1 underline" onClick={() => void check()}>
                <Icon name="refresh" size={12} /> run again
              </button>
            </span>
          ) : (
            <span className="flex items-center gap-2 text-fg">
              <Spinner className="h-3 w-3" /> checking {job.pct}% {job.msg ? `· ${job.msg}` : ""}
            </span>
          )
        ) : r ? (
          <span title={new Date(String(r.created_at)).toLocaleString()}>
            {r.results.length - r.summary.not_applicable} clauses · checked {new Date(String(r.created_at)).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        ) : (
          <span>not checked yet</span>
        )}
        {fsi && fsi.used !== null && (
          <span className={fsiOver ? "text-danger" : ""}>
            FSI {fsi.used.toFixed(2)} / {fsi.base_permissible ?? "?"} base · {fsi.max_permissible ?? "?"} max
          </span>
        )}
        {pack.data?.height.current_m != null && <span>height {pack.data.height.current_m.toFixed(1)} m</span>}
        {short !== null && <span className={short ? "text-danger" : ""}>{short ? `${short} side${short > 1 ? "s" : ""} inside the margin` : "margins clear"}</span>}
        {error ? <span className="text-danger">{String((error as Error).message ?? error)}</span> : null}
        <span className="ml-auto shrink-0">{m ? `${m.meta.source_kind.toUpperCase()} · ` : ""}PMC · UDCPR 2020</span>
      </footer>

      {site && m && project.data && (
        <SiteWizard projectId={projectId} model={m} brief={project.data.brief} busy={busy} onClose={() => setSite(false)} onSave={(a) => void check(a)} onSaveOnly={saveSite} />
      )}
    </Shell>
  );
}

// The card opens beside the click, kept inside the canvas; from the list it docks at the right.
// In 2D it stays below the floor tabs (`inset`).
function place(card: Card, host: HTMLDivElement | null, inset = 0): React.CSSProperties {
  if (card.x === null || card.y === null || !host) return { right: 0, top: inset, maxHeight: `calc(100% - ${inset}px)` };
  const w = 380, h = Math.min(420, host.clientHeight - 24);
  const left = card.x + 16 + w > host.clientWidth - 12 ? Math.max(0, card.x - w - 16) : card.x + 4;
  const top = Math.max(inset, Math.min(card.y - 24, host.clientHeight - 24 - h));
  return { left, top, maxHeight: h };
}

// Rooms on one floor that fail in the same way (a whole storey built too low) are one row, opened
// to list the rooms; each room still opens its own card.
function IssueList({ groups, selected, allClear, onPick }: { groups: Group[]; selected?: string; allClear: boolean; onPick: (g: Group) => void }) {
  const [openRows, setOpenRows] = useState<Set<string>>(new Set());
  const list = useMemo(() => bunchGroups(groups), [groups]);
  const toggle = (key: string) =>
    setOpenRows((s) => {
      const n = new Set(s);
      if (n.has(key)) n.delete(key);
      else n.add(key);
      return n;
    });
  const item = (g: Group, indent = false) => {
    const fails = g.results.filter((x) => x.status === "fail").length;
    return (
      <li key={g.key}>
        <button
          onClick={() => onPick(g)}
          className={`flex w-full items-center gap-2 py-2 pr-3 text-left text-sm hover:bg-surface-raised ${indent ? "pl-8" : "pl-3"} ${g.key === selected ? "bg-surface-raised" : ""}`}
        >
          <StatusMark status={g.worst} short />
          <span className="min-w-0 flex-1">
            <span className="block truncate">{g.name}</span>
            {g.detail && !indent && <span className="block truncate text-2xs text-fg-3">{g.detail}</span>}
          </span>
          {fails > 1 && <span className="num text-xs text-danger">{fails}</span>}
        </button>
      </li>
    );
  };
  return (
    <aside className="absolute bottom-3 left-3 top-14 z-[550] flex w-64 flex-col overflow-hidden rounded-md border border-line-subtle bg-surface/95 backdrop-blur">
      <p className="label border-b border-line-subtle px-3 py-2">{allClear ? "no issues" : `${list.length} to look at`}</p>
      <ul className="min-h-0 flex-1 overflow-y-auto">
        {allClear && <li className="px-3 py-3 text-xs text-fg-2">Every clause that applies passes. Turn on “show passes” to see them.</li>}
        {list.map((row) => {
          if (!isBunch(row)) return item(row);
          const isOpen = openRows.has(row.key) || row.members.some((m) => m.key === selected);
          return (
            <li key={row.key}>
              <button
                onClick={() => toggle(row.key)}
                aria-expanded={isOpen}
                className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-raised"
              >
                <StatusMark status={row.worst} short />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">
                    {row.floor || "rooms"} · {row.members.length} rooms
                  </span>
                  <span className="block truncate text-2xs text-fg-3">{row.title.toLowerCase()}</span>
                </span>
                <span className={`text-fg-3 transition-transform ${isOpen ? "rotate-90" : ""}`}>
                  <Icon name="chevron" size={14} />
                </span>
              </button>
              {isOpen && <ul className="border-l border-line-subtle">{row.members.map((m) => item(m, true))}</ul>}
            </li>
          );
        })}
      </ul>
    </aside>
  );
}

// The project's name (click to rename; saved on the server) and a copy-link button.
function ProjectName({ id, name, onRenamed }: { id: string; name: string; onRenamed: () => void }) {
  const [edit, setEdit] = useState(false);
  const [text, setText] = useState(name);
  const [copied, setCopied] = useState(false);
  useEffect(() => setText(name), [name]);
  async function save() {
    setEdit(false);
    if (!text.trim() || text.trim() === name) return setText(name);
    const r = await api.renameProject(id, text);
    rememberProject({ id, name: r.name });
    onRenamed();
  }
  return (
    <span className="flex items-center gap-1">
      {edit ? (
        <input
          className="input h-7 w-[220px] py-0 text-sm"
          value={text}
          autoFocus
          onChange={(e) => setText(e.target.value)}
          onBlur={() => void save()}
          onKeyDown={(e) => {
            if (e.key === "Enter") void save();
            if (e.key === "Escape") {
              setText(name);
              setEdit(false);
            }
          }}
          aria-label="project name"
        />
      ) : (
        <button className="max-w-[220px] truncate text-sm font-medium hover:underline" title="Rename" onClick={() => setEdit(true)}>
          {name}
        </button>
      )}
      <button
        className="btn-ghost h-7 px-1.5"
        title={copied ? "Link copied" : "Copy this project's link (it opens the saved project on any device)"}
        onClick={() => {
          void navigator.clipboard?.writeText(`${window.location.origin}/w/${id}`);
          setCopied(true);
          setTimeout(() => setCopied(false), 1500);
        }}
        aria-label="copy link"
      >
        <Icon name={copied ? "check" : "link"} size={13} />
      </button>
    </span>
  );
}

function Shell({ children }: { children: ReactNode }) {
  return <div className="fixed inset-0 flex flex-col bg-canvas text-fg">{children}</div>;
}
function Sep() {
  return <span className="mx-1 h-5 w-px bg-line-subtle" aria-hidden />;
}
function Seg({ children }: { children: ReactNode }) {
  return <div className="flex h-8 items-center rounded-sm border border-line-subtle p-0.5">{children}</div>;
}
function SegBtn({ on, onClick, title, children }: { on: boolean; onClick: () => void; title?: string; children: ReactNode }) {
  return (
    <button
      onClick={onClick}
      aria-pressed={on}
      title={title}
      className={`flex h-full items-center gap-1.5 rounded-[1px] px-2 text-xs transition-colors ${on ? "bg-surface-raised text-fg" : "text-fg-3 hover:text-fg"}`}
    >
      {children}
    </button>
  );
}
