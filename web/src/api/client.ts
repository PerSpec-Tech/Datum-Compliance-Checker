// Typed client for the FastAPI backend. Contract types come from the generated
// file; the small response wrappers below mirror backend/src/compliance/api/routes.py.
import type {
  BuildingModel,
  CheckReport,
  Clause,
  Freshness,
  Fact,
  LivePack,
  RuleStatus,
  Severity,
} from "./types";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`/api${path}`, init);
  if (!res.ok) {
    let detail = res.statusText;
    try {
      const body = await res.json();
      detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail);
    } catch {
      /* not JSON */
    }
    throw new ApiError(res.status, detail || `HTTP ${res.status}`);
  }
  return (await res.json()) as T;
}

const json = (method: string, body: unknown): RequestInit => ({
  method,
  headers: { "Content-Type": "application/json" },
  body: JSON.stringify(body),
});

export interface ProjectInfo {
  id: string;
  name: string;
  created_at: string;
  latest_model_version: string | null;
  latest_report_id: string | null;
  brief: Record<string, Fact<unknown>>;
}

// Where an upload is while the server reads it (GET /projects/{id}/reading).
export type ReadingStatus =
  | { state: "idle" }
  | { state: "queued"; ahead: number; reading: number }
  | { state: "reading"; pct: number; msg: string | null }
  | { state: "done"; result: UploadResult }
  | { state: "failed"; status: number; detail: string };

// What uploadModel reports while it works: the bytes going up, then the server's read.
export type UploadProgress =
  | { state: "uploading"; pct: number }
  | { state: "queued"; ahead: number; reading: number }
  | { state: "reading"; pct: number; msg: string | null };

type Answer = { status: number; body: unknown };
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));
const detailOf = (body: unknown, status: number) => {
  const d = (body as { detail?: unknown } | null)?.detail;
  return typeof d === "string" ? d : d ? JSON.stringify(d) : `HTTP ${status}`;
};

/** POST a file with upload progress (fetch can't report it). */
function postFile(path: string, file: Blob, onSent: (fraction: number) => void): Promise<Answer> {
  return new Promise((resolve, reject) => {
    const x = new XMLHttpRequest();
    x.open("POST", `/api${path}`);
    x.setRequestHeader("Content-Type", "application/octet-stream");
    x.upload.onprogress = (e) => e.lengthComputable && onSent(e.loaded / e.total);
    x.upload.onload = () => onSent(1);
    x.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(x.responseText);
      } catch {
        /* not JSON: a proxy's error page */
      }
      resolve({ status: x.status, body });
    };
    x.onerror = () => reject(new ApiError(0, "The upload didn't reach the server. Check your connection and try again."));
    x.send(file);
  });
}

/** Upload a model and follow the server's read to the end. A long read answers 202 and carries
 *  on; the result then comes from GET /reading. The same applies when a proxy cuts the request
 *  after the file arrived: the server is still reading it. */
async function uploadModel(
  id: string,
  kind: "ifc" | "dxf",
  file: Blob,
  on: (p: UploadProgress) => void = () => undefined,
): Promise<UploadResult> {
  const ctl = { sent: false, accepted: false, stop: false };
  const posting = postFile(`/projects/${id}/${kind}`, file, (f) => {
    if (f >= 1) ctl.sent = true;
    else on({ state: "uploading", pct: Math.round(f * 100) });
  });
  const polling = (async (): Promise<Answer> => {
    let idle = 0;
    while (!ctl.stop) {
      await sleep(1000);
      if (!ctl.sent || ctl.stop) continue;
      let s: ReadingStatus;
      try {
        s = await request<ReadingStatus>(`/projects/${id}/reading`);
      } catch {
        continue; // a missed poll; try again
      }
      if (ctl.stop) break;
      if (s.state === "done") return { status: 200, body: s.result };
      if (s.state === "failed") return { status: s.status, body: { detail: s.detail } };
      if (s.state === "idle") {
        if (ctl.accepted && ++idle >= 5)
          return { status: 0, body: { detail: "The server restarted while reading this model. Please upload it again." } };
        continue;
      }
      idle = 0;
      on(s);
    }
    return { status: 0, body: null };
  })();
  try {
    let answer: Answer;
    try {
      answer = await Promise.race([posting, polling]);
    } catch (e) {
      if (!ctl.sent) throw e;
      answer = { status: 502, body: null }; // the file arrived; follow the read
    }
    if (answer.status === 202 || (ctl.sent && (answer.status === 502 || answer.status === 504))) {
      ctl.accepted = true;
      answer = await polling;
    }
    if (answer.status >= 200 && answer.status < 300) return answer.body as UploadResult;
    throw new ApiError(answer.status, detailOf(answer.body, answer.status));
  } finally {
    ctl.stop = true;
  }
}

export interface UploadResult {
  model_version: string;
  warnings: string[];
  counts: Record<string, number>;
  has_site_boundary: boolean;
  // DXF only: every layer with its role (null = not understood yet)
  layers?: {
    layer: string;
    role: string | null;
    // predcr = official layer name · user = you chose it · suggested = Nemotron's guess (shown dashed)
    source: "predcr" | "user" | "suggested" | null;
    confidence?: number | null;
    entities: number;
  }[];
  unmapped?: number;
}

export const LAYER_ROLES = [
  "plot", "road", "footprint", "floor", "floor_height", "ground", "fsi_resi", "fsi_comm",
  "fsi_other", "carpet", "room", "door", "window", "stair", "balcony", "parking", "ignore",
] as const;

export interface JobEvent {
  stage: string;
  pct?: number;
  msg?: string;
  report_id?: string;
  error?: string;
}

export interface RuleSummary {
  id: string;
  title: string;
  ruleset: string;
  kind: "check" | "advisory";
  severity: Severity;
  status: RuleStatus;
  clause: Clause;
  for_each: string | null;
  expressions: Partial<Record<"applies_when" | "limit" | "measured" | "check", string>>;
  compiled_by: string;
  freshness: Freshness | null;
  requires: string[];
}

export interface RuleDetail extends RuleSummary {
  doc: Record<string, unknown>;
  tables: Record<string, unknown>;
}

export interface CompileResult {
  ok: boolean;
  rule: Record<string, unknown> | null;
  tables: Record<string, unknown>[];
  errors: string[];
  dry_run: unknown;
  attempts: number;
  notes: string | string[];
  review: { verdict?: string; issues?: string[]; notes?: string[]; [k: string]: unknown } | null;
  review_history: unknown[];
  history: unknown[];
}

export interface Mesh {
  guid: string;
  parent: string | null;
  type: string;
  name: string;
  v: number[];
  f: number[];
}

export interface City {
  id: string;
  city: string;
  authority: string;
  center: { lat: number; lon: number } | null;
}

export interface Place {
  label: string;
  lat: number;
  lon: number;
}

/** An address suggestion as you type: an address or street is `precise`; an area has its extent. */
export interface Suggest extends Place {
  kind: string;
  precise: boolean;
  extent: [number, number, number, number] | null; // west, south, east, north
}

export interface ProjectSummary {
  id: string;
  name: string;
  created_at: string;
  updated_at: string;
  source_kind: "ifc" | "dxf" | "revit" | string | null;
  location: { lat: number; lon: number } | null;
  site: { location: boolean; plot: boolean; sides: boolean };
  last_check: { report_id: string; at: string; fail?: number; unverifiable?: number; pass?: number } | null;
}

export interface Orientation {
  rotation_deg: number | null;
  source: string | null;
}

export interface Located {
  authority_id: string | null;
  note: string;
  label: string | null;
}

// GET /projects/{id}/drawing: the uploaded DXF as vectors per floor plan.
export interface DrawingFloor {
  nums: number[];
  name: string | null;
  paths: Record<string, number[][]>; // class → polylines as flat [x, y, x, y, …]
  fills: number[][];
  texts: [number, number, number, number, string, string][]; // x, y, height, rotation, text, class
}

/** A planning fact the checker suggests, with what the model has now. */
export interface Suggestion {
  path: string;
  suggested: Fact<unknown>;
  current: Fact<unknown>;
}

export const api = {
  drawing: (id: string) => request<{ floors: DrawingFloor[] }>(`/projects/${id}/drawing`),
  cities: () => request<City[]>("/cities"),
  geocode: (q: string, authority: string) =>
    request<Place[]>(`/geocode?${new URLSearchParams({ q, authority })}`),
  locate: (lat: number, lon: number) => request<Located>(`/locate?lat=${lat}&lon=${lon}`),
  suggest: (q: string, authority: string, signal?: AbortSignal) =>
    request<Suggest[]>(`/suggest?${new URLSearchParams({ q, authority })}`, { signal }),
  orientation: (id: string) => request<Orientation>(`/projects/${id}/orientation`),
  projectSummaries: (ids: string[]) => request<ProjectSummary[]>(`/project-summaries?ids=${ids.map(encodeURIComponent).join(",")}`),
  renameProject: (id: string, name: string) => request<{ id: string; name: string }>(`/projects/${id}`, json("PATCH", { name })),
  livePack: (id: string) => request<LivePack>(`/projects/${id}/live-pack`),
  suggestions: (id: string, lat: number, lon: number) =>
    request<Suggestion[]>(`/projects/${id}/suggestions?lat=${lat}&lon=${lon}`),
  health: () => request<{ ok: boolean; rules: number; ruleset_version: string }>("/health"),
  pairStart: () => request<{ code: string; expires_in_s: number }>("/pair/start", { method: "POST" }),
  createProject: (name: string) => request<{ id: string }>("/projects", json("POST", { name })),
  project: (id: string) => request<ProjectInfo>(`/projects/${id}`),
  model: (id: string) =>
    request<{ model_version: string; model: BuildingModel; skipped_answers: string[] }>(
      `/projects/${id}/model`,
    ),
  reading: (id: string) => request<ReadingStatus>(`/projects/${id}/reading`),
  uploadIfc: (id: string, file: Blob, on?: (p: UploadProgress) => void) => uploadModel(id, "ifc", file, on),
  uploadDxf: (id: string, file: Blob, on?: (p: UploadProgress) => void) => uploadModel(id, "dxf", file, on),
  setDxfRoles: (id: string, roles: Record<string, string | null>) =>
    request<UploadResult>(`/projects/${id}/dxf/roles`, json("PUT", roles)),
  patchBrief: (id: string, answers: Record<string, unknown>) =>
    request<{ brief: Record<string, Fact<unknown>> }>(`/projects/${id}/brief`, json("PATCH", answers)),
  startCheck: (id: string) => request<{ job_id: string }>(`/projects/${id}/checks`, { method: "POST" }),
  report: (id: string) => request<CheckReport>(`/reports/${id}`),
  mesh: (version: string) =>
    request<{ elements: Mesh[]; spaces: Mesh[]; context: Mesh[] }>(`/models/${version}/mesh`),
  rules: () => request<RuleSummary[]>("/rules"),
  rule: (id: string) => request<RuleDetail>(`/rules/${encodeURIComponent(id)}`),
  compile: (body: {
    clause_text: string;
    clause_ref: string;
    source: string;
    authority: string;
    review: boolean;
  }) => request<CompileResult>("/rules/compile", json("POST", body)),
  bcfUrl: (reportId: string) => `/api/reports/${reportId}/bcf`,
  eventsUrl: (jobId: string) => `/api/jobs/${jobId}/events`,
};
