import { useState, type DragEvent } from "react";
import { Link, useNavigate } from "react-router-dom";
import { LAYER_ROLES, api, type UploadResult } from "../../api/client";
import { FieldError, Icon, Spinner, Title } from "../../components/ui";
import { recentProjects, rememberProject } from "../../lib/recent";
import Sketch from "../../components/Sketch";
import type { LatLon } from "../brief/MapPin";

// Start: pick a model or a sample (guidelines §12: centred column, one primary action).

const SAMPLES = [
  {
    file: "demo_apartment.ifc",
    name: "mixed-use block near a metro station",
    facts: "IFC · G+4 · 2 shops · 24 flats",
    blurb: "Site and planning facts are modelled. 9 issues to find.",
  },
  {
    file: "demo_house.dxf",
    name: "two-storey bungalow",
    facts: "DXF · PreDCR layers · plans + section",
    blurb: "How most drawings arrive. Set the location next.",
  },
];

const isDxf = (name: string) => /\.dxf$/i.test(name);

interface Loaded {
  id: string;
  name: string;
  upload: UploadResult;
  location: LatLon | null;
  dxf: boolean;
}

// Upload, then straight into the workspace (P12.4). The check starts at once when the model knows
// where it is; otherwise the workspace opens on "set the site". A drawing whose layers need a look
// stops here first.
export default function NewCheckPage() {
  const navigate = useNavigate();
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  async function load(file: Blob, name: string, fileName = name) {
    setError(null);
    try {
      setBusy("creating the project");
      const { id } = await api.createProject(name.replace(/\.(ifc|dxf)$/i, ""));
      rememberProject({ id, name });
      const dxf = isDxf(fileName);
      setBusy(dxf ? "reading the 2D drawing" : "reading the IFC model");
      const upload = dxf ? await api.uploadDxf(id, file) : await api.uploadIfc(id, file);
      const m = await api.model(id);
      const loc = m.model.project.location.value;
      const l = { id, name, upload, location: loc ? { lat: loc.lat, lon: loc.lon } : null, dxf };
      const attention = dxf && ((upload.unmapped ?? 0) > 0 || upload.layers?.some((x) => x.source === "suggested"));
      if (attention) setLoaded(l);
      else await open(l);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }

  async function open(l: Loaded) {
    setBusy("opening the workspace");
    if (l.location) {
      const { job_id } = await api.startCheck(l.id);
      navigate(`/w/${l.id}?job=${job_id}`);
    } else navigate(`/w/${l.id}`);
  }

  async function sample(file: string, name: string) {
    setError(null);
    setBusy("fetching the sample");
    try {
      const res = await fetch(`/samples/${file}`);
      if (!res.ok) throw new Error(`Sample not found (${res.status}).`);
      await load(await res.blob(), name, file);
    } catch (e) {
      setError(e);
      setBusy(null);
    }
  }

  return (
    <div className="mx-auto max-w-[920px]">
      <ModelStep
        loaded={loaded}
        busy={busy}
        error={error}
        onFile={(f) => void load(f, f.name)}
        onSample={(f, n) => void sample(f, n)}
        onReset={() => setLoaded(null)}
        onRemapped={(upload) => setLoaded((l) => (l ? { ...l, upload } : l))}
        onNext={() => loaded && void open(loaded).catch(setError)}
      />
    </div>
  );
}

function ModelStep({
  loaded,
  busy,
  error,
  onFile,
  onSample,
  onReset,
  onRemapped,
  onNext,
}: {
  loaded: Loaded | null;
  busy: string | null;
  error: unknown;
  onFile: (f: File) => void;
  onSample: (file: string, name: string) => void;
  onReset: () => void;
  onRemapped: (u: UploadResult) => void;
  onNext: () => void;
}) {
  const [dragging, setDragging] = useState(false);
  const recent = recentProjects();

  if (loaded) {
    const c = loaded.upload.counts;
    return (
      <section>
        <Title>model loaded.</Title>
        <div className="panel mt-6 divide-y divide-line-subtle">
          <Row k="file" v={loaded.name} />
          <Row
            k="read"
            v={
              <span className="num">
                {c.levels} storeys · {c.spaces} rooms · {c.doors} doors · {c.stairs} stairs · {c.units} units
              </span>
            }
          />
          <Row
            k="site"
            v={loaded.upload.has_site_boundary ? "plot boundary found" : <span className="text-fg-2">no plot boundary in the model</span>}
          />
          <Row
            k="location"
            v={
              loaded.location ? (
                <span className="num">
                  {loaded.location.lat.toFixed(5)}, {loaded.location.lon.toFixed(5)}
                </span>
              ) : (
                <span className="text-fg-2">not in the model. set it on the map next</span>
              )
            }
          />
        </div>
        {loaded.dxf && loaded.upload.layers && <LayerTable loaded={loaded} onRemapped={onRemapped} />}
        {loaded.upload.warnings.length > 0 && (
          <ul className="mt-3 space-y-1 text-xs text-fg-2">
            {loaded.upload.warnings.map((w) => (
              <li key={w} className="flex gap-2">
                <Icon name="info" size={14} className="mt-px" /> {w}
              </li>
            ))}
          </ul>
        )}
        <div className="mt-8 flex justify-between">
          <button className="btn-secondary" onClick={onReset}>
            <Icon name="back" /> change model
          </button>
          <button className="btn-primary" onClick={onNext} disabled={!!busy}>
            {busy ? <Spinner /> : null} open <Icon name="arrow" />
          </button>
        </div>
      </section>
    );
  }

  function drop(e: DragEvent) {
    e.preventDefault();
    setDragging(false);
    const f = e.dataTransfer.files[0];
    if (f) onFile(f);
  }

  return (
    <section>
      <Title>add a model.</Title>

      <label
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={drop}
        className={`mt-6 flex cursor-pointer items-center gap-6 rounded-md border border-dashed px-8 py-8 transition-colors ${
          dragging ? "border-fg bg-surface-raised" : "border-line bg-surface hover:border-line-strong"
        } ${busy ? "pointer-events-none" : ""}`}
      >
        <span className="grid h-16 w-16 shrink-0 place-items-center rounded-md border border-line-subtle bg-surface-low text-fg-2">
          {busy ? <Spinner className="h-6 w-6" /> : <Icon name="upload" size={28} />}
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-base font-medium">{busy ?? "drop a model here"}</span>
          <span className="mt-1 flex flex-wrap gap-2 text-xs text-fg-2">
            <span className="flex items-center gap-1.5 rounded-sm border border-line-subtle px-2 py-1">
              <Icon name="cube" size={14} /> IFC from Revit, ArchiCAD…
            </span>
            <span className="flex items-center gap-1.5 rounded-sm border border-line-subtle px-2 py-1">
              <Icon name="layers" size={14} /> DXF from AutoCAD (PreDCR or your layers)
            </span>
          </span>
        </span>
        {!busy && (
          <span className="btn-secondary shrink-0">
            <Icon name="search" /> browse
          </span>
        )}
        <input
          type="file"
          accept=".ifc,.dxf"
          className="sr-only"
          disabled={!!busy}
          onChange={(e) => {
            const f = e.target.files?.[0];
            if (f) onFile(f);
          }}
        />
      </label>
      {error ? <FieldError error={error} /> : null}

      <p className="label mt-10">or try a sample</p>
      <div className="grid gap-4 sm:grid-cols-2">
        {SAMPLES.map((s) => (
          <button
            key={s.file}
            disabled={!!busy}
            onClick={() => onSample(s.file, s.name)}
            className="group flex flex-col overflow-hidden rounded-md border border-line-subtle bg-surface text-left transition-colors hover:border-line-strong disabled:opacity-50"
          >
            <span className="relative block h-48 bg-surface-low">
              <Sketch src={`/samples/${s.file}.${s.file.endsWith(".dxf") ? "svg" : "png"}`} className="h-full w-full p-3" />
              <span className="absolute left-3 top-3 flex items-center gap-1.5 rounded-sm border border-line-subtle bg-surface px-2 py-0.5 font-mono text-2xs text-fg-2">
                <Icon name={s.file.endsWith(".dxf") ? "layers" : "cube"} size={12} />
                {s.file.endsWith(".dxf") ? "DXF · 2D" : "IFC · 3D"}
              </span>
            </span>
            <span className="flex items-center gap-3 border-t border-line-subtle px-4 py-3">
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{s.name}</span>
                <span className="block font-mono text-2xs text-fg-3">{s.facts}</span>
              </span>
              <Icon name="arrow" className="text-fg-3 transition-colors group-hover:text-fg" />
            </span>
          </button>
        ))}
      </div>

      {recent.length > 0 && (
        <>
          <p className="label mt-10">recent projects</p>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {recent.slice(0, 8).map((r) => (
              <Link
                key={r.id}
                to={`/w/${r.id}`}
                className="group flex flex-col overflow-hidden rounded-md border border-line-subtle bg-surface transition-colors hover:border-line-strong"
              >
                <Sketch src={`/api/projects/${r.id}/thumbnail`} className="h-32 w-full bg-surface-low p-3" />
                <span className="flex items-center gap-2 border-t border-line-subtle px-3 py-2">
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm">{r.name}</span>
                    <span className="block font-mono text-2xs text-fg-3">{new Date(r.at).toLocaleDateString()}</span>
                  </span>
                  <Icon name="arrow" size={14} className="text-fg-3 group-hover:text-fg" />
                </span>
              </Link>
            ))}
          </div>
        </>
      )}
    </section>
  );
}

function LayerTable({ loaded, onRemapped }: { loaded: Loaded; onRemapped: (u: UploadResult) => void }) {
  const [saving, setSaving] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const layers = loaded.upload.layers ?? [];
  const unmapped = layers.filter((l) => l.role === null);
  const suggested = layers.filter((l) => l.source === "suggested");
  const [open, setOpen] = useState(unmapped.length > 0 || suggested.length > 0);

  async function confirmAll() {
    setSaving("*");
    setErr(null);
    try {
      onRemapped(await api.setDxfRoles(loaded.id, Object.fromEntries(suggested.map((l) => [l.layer, l.role]))));
    } catch (e) {
      setErr(e);
    } finally {
      setSaving(null);
    }
  }

  async function setRole(layer: string, role: string) {
    setSaving(layer);
    setErr(null);
    try {
      onRemapped(await api.setDxfRoles(loaded.id, { [layer]: role || null }));
    } catch (e) {
      setErr(e);
    } finally {
      setSaving(null);
    }
  }

  return (
    <div className="panel mt-3">
      <button className="flex w-full items-center justify-between px-4 py-2.5 text-left text-sm" onClick={() => setOpen((o) => !o)}>
        <span>
          layers <span className="num text-fg-2">{layers.length}</span>
          {unmapped.length > 0 && <span className="ml-2 text-xs text-fg">· {unmapped.length} not understood</span>}
          {suggested.length > 0 && (
            <span className="ml-2 text-xs text-fg-2">· {suggested.length} suggested</span>
          )}
        </span>
        <Icon name="chevron" size={14} className={open ? "rotate-180" : ""} />
      </button>
      {open && suggested.length > 0 && (
        <div className="flex items-center justify-between gap-3 border-t border-line-subtle px-4 py-2 text-xs text-fg-2">
          <span title="Suggested by Nemotron from each layer's name and contents">dashed = suggested</span>
          <button className="btn-secondary h-7 shrink-0 px-2.5 text-xs" disabled={saving !== null} onClick={() => void confirmAll()}>
            {saving === "*" ? <Spinner className="h-3.5 w-3.5" /> : <Icon name="check" size={14} />} confirm all
          </button>
        </div>
      )}
      {open && (
        <ul className="max-h-72 divide-y divide-line-subtle overflow-y-auto border-t border-line-subtle">
          {layers.map((l) => (
            <li key={l.layer} className="flex items-center gap-3 px-4 py-1.5">
              <span className="min-w-0 flex-1 truncate font-mono text-xs">{l.layer}</span>
              <span className="num w-10 text-right text-fg-3">{l.entities}</span>
              <span className="w-20 text-right font-mono text-2xs text-fg-3" title="where the role came from">
                {l.source === "suggested"
                  ? `predicted ${Math.round((l.confidence ?? 0) * 100)}%`
                  : l.source === "predcr"
                    ? "PreDCR"
                    : l.source === "user"
                      ? "yours"
                      : ""}
              </span>
              <select
                className={`input h-7 w-36 py-0 text-xs ${l.role === null || l.source === "suggested" ? "border-dashed" : ""}`}
                value={l.role ?? ""}
                disabled={saving !== null}
                onChange={(e) => void setRole(l.layer, e.target.value)}
              >
                <option value="">not set</option>
                {LAYER_ROLES.map((r) => (
                  <option key={r} value={r}>
                    {r.replace("_", " ")}
                  </option>
                ))}
              </select>
              {saving === l.layer && <Spinner className="h-3.5 w-3.5" />}
            </li>
          ))}
        </ul>
      )}
      {err ? <div className="px-4 pb-3"><FieldError error={err} /></div> : null}
    </div>
  );
}

function Row({ k, v }: { k: string; v: React.ReactNode }) {
  return (
    <div className="flex items-baseline gap-4 px-4 py-2.5 text-sm">
      <span className="w-20 shrink-0 text-xs text-fg-2">{k}</span>
      <span className="min-w-0 flex-1">{v}</span>
    </div>
  );
}
