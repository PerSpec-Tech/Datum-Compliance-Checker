import { useEffect, useState } from "react";
import { Link, useLocation, useNavigate, useParams } from "react-router-dom";
import { api, type JobEvent } from "../../api/client";
import { Icon, Spinner, Title } from "../../components/ui";
import { rememberProject } from "../../lib/recent";

// A genuine ML job: named steps, progress tied to real stages, safe to leave and come back (§10).
const STAGES: { key: string; label: string; who: string }[] = [
  { key: "resolve_authority", label: "find the planning authority", who: "Nominatim + authority table" },
  { key: "overlays", label: "metro TOD and other overlays", who: "OSM metro stations" },
  { key: "classify_usage", label: "classify unnamed rooms", who: "Nemotron Nano" },
  { key: "derive", label: "measure the model", who: "rule engine" },
  { key: "evaluate", label: "evaluate the rules", who: "rule engine" },
  { key: "freshness", label: "check the rules are current", who: "Tavily + Nemotron Nano" },
  { key: "plan_questions", label: "plan questions for missing facts", who: "rule engine + Nemotron Nano" },
  { key: "explain", label: "word the results", who: "Nemotron Super" },
];

export default function ProgressPage() {
  const { projectId, jobId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const warnings = (location.state as { warnings?: string[] } | null)?.warnings ?? [];
  const [events, setEvents] = useState<JobEvent[]>([]);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!jobId) return;
    const es = new EventSource(api.eventsUrl(jobId));
    es.onmessage = (m) => {
      const e = JSON.parse(m.data) as JobEvent;
      setEvents((prev) => [...prev, e]);
      if (e.stage === "done" && e.report_id) {
        es.close();
        if (projectId) rememberProject({ id: projectId, name: "", reportId: e.report_id });
        setTimeout(() => navigate(`/reports/${e.report_id}`, { replace: true }), 500);
      } else if (e.stage === "error") {
        es.close();
        setError(e.error ?? e.msg ?? "The check failed.");
      }
    };
    es.onerror = () => {
      es.close();
      setError((prev) => prev ?? "Lost the connection to the server.");
    };
    return () => es.close();
  }, [jobId, projectId, navigate, attempt]);

  const seen = new Set(events.map((e) => e.stage));
  const last = events.length ? events[events.length - 1] : null;
  const pct = Math.round(last?.stage === "done" ? 100 : (last?.pct ?? 0));
  const lastMsg = (stage: string) => [...events].reverse().find((e) => e.stage === stage)?.msg;

  async function retry() {
    if (!projectId) return;
    setError(null);
    setEvents([]);
    const { job_id } = await api.startCheck(projectId);
    navigate(`/p/${projectId}/jobs/${job_id}`, { replace: true });
    setAttempt((a) => a + 1);
  }

  return (
    <div className="mx-auto max-w-[600px]">
      <Title>checking the model.</Title>
      <p className="mt-2 text-sm text-fg-2">Safe to leave this page; the report is kept with the project.</p>

      <div className="mt-6 flex items-center gap-3">
        <div className="h-[2px] flex-1 bg-line-subtle">
          <div className="h-full bg-accent transition-[width] duration-500" style={{ width: `${pct}%` }} />
        </div>
        <span className="num w-10 text-right text-fg-2">{pct}%</span>
      </div>

      {warnings.length > 0 && (
        <ul className="mt-4 space-y-1 text-xs text-fg-2">
          {warnings.map((w) => (
            <li key={w} className="flex gap-2">
              <Icon name="info" size={14} className="mt-px" /> {w}
            </li>
          ))}
        </ul>
      )}

      {error ? (
        <div className="panel mt-6 p-5">
          <div className="flex items-start gap-3">
            <Icon name="x" className="mt-0.5 text-danger" />
            <div className="min-w-0 flex-1">
              <p className="h2">the check stopped</p>
              <p className="mt-1 text-sm text-fg-2">{error}</p>
            </div>
          </div>
          <div className="mt-4 flex gap-2">
            <button className="btn-secondary" onClick={() => void retry()}>
              <Icon name="refresh" /> run again
            </button>
            {projectId && (
              <Link to={`/p/${projectId}/brief`} className="btn-ghost">
                open the brief
              </Link>
            )}
          </div>
        </div>
      ) : null}

      <ol className="panel mt-6 divide-y divide-line-subtle">
        {STAGES.map((s, i) => {
          const later = STAGES.slice(i + 1).some((x) => seen.has(x.key)) || seen.has("done");
          const state = later ? "done" : seen.has(s.key) ? (error ? "error" : "active") : "waiting";
          return (
            <li key={s.key} className="flex items-start gap-3 px-4 py-3">
              <span className="num w-6 pt-px text-fg-3">{String(i + 1).padStart(2, "0")}</span>
              <span className="grid h-5 w-5 shrink-0 place-items-center">
                {state === "done" && <Icon name="check" size={14} className="text-fg" />}
                {state === "active" && <Spinner className="h-3.5 w-3.5 text-fg" />}
                {state === "error" && <Icon name="x" size={14} className="text-danger" />}
                {state === "waiting" && <span className="h-1 w-1 bg-fg-off" />}
              </span>
              <div className="min-w-0 flex-1">
                <p className={`text-sm ${state === "waiting" ? "text-fg-off" : "text-fg"}`}>{s.label}</p>
                <p className="mt-0.5 text-xs text-fg-3">{state !== "waiting" && lastMsg(s.key) ? lastMsg(s.key) : s.who}</p>
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}
