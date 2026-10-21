import { useEffect, useState, type DragEvent, type FormEvent } from "react";
import { useQuery } from "@tanstack/react-query";
import { Link, useNavigate } from "react-router-dom";
import { LAYER_ROLES, api, type Place, type UploadResult } from "../../api/client";
import { Chip, ErrorBox, FieldError, Icon, Spinner, Title } from "../../components/ui";
import { recentProjects, rememberProject } from "../../lib/recent";
import MapPin, { type LatLon } from "../brief/MapPin";

// Wizard / setup flow (guidelines §12): centred column, numbered steps, one primary action per step.

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

// Pilot: Pune only. The rest are shown so the scope is honest, and greyed out.
const COMING = ["Pimpri-Chinchwad", "Mumbai", "Thane", "Nashik", "Nagpur", "Bengaluru", "Delhi"];

const STEPS = ["model", "location", "check"] as const;
type Step = 0 | 1 | 2;

interface Loaded {
  id: string;
  name: string;
  upload: UploadResult;
  location: LatLon | null;
  dxf: boolean;
}

export default function NewCheckPage() {
  const navigate = useNavigate();
  const [step, setStep] = useState<Step>(0);
  const [loaded, setLoaded] = useState<Loaded | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [city, setCity] = useState("pmc");
  const [pin, setPin] = useState<LatLon | null>(null);
  const [running, setRunning] = useState(false);

  async function load(file: Blob, name: string, fileName = name) {
    setError(null);
    try {
      setBusy("creating the project");
      const { id } = await api.createProject(name.replace(/\.ifc$/i, ""));
      rememberProject({ id, name });
      const dxf = isDxf(fileName);
      setBusy(dxf ? "reading the 2D drawing" : "reading the IFC model");
      const upload = dxf ? await api.uploadDxf(id, file) : await api.uploadIfc(id, file);
      const m = await api.model(id);
      const loc = m.model.project.location.value;
      setLoaded({ id, name, upload, location: loc ? { lat: loc.lat, lon: loc.lon } : null, dxf });
      setPin(loc ? { lat: loc.lat, lon: loc.lon } : null);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
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

  async function run() {
    if (!loaded || !pin) return;
    setRunning(true);
    setError(null);
    try {
      const moved = !loaded.location || loaded.location.lat !== pin.lat || loaded.location.lon !== pin.lon;
      if (moved) await api.patchBrief(loaded.id, { "project.location": pin });
      const { job_id } = await api.startCheck(loaded.id);
      navigate(`/p/${loaded.id}/jobs/${job_id}`, { state: { warnings: loaded.upload.warnings } });
    } catch (e) {
      setError(e);
      setRunning(false);
    }
  }

  return (
    <div className="mx-auto max-w-[600px]">
      <ol className="mb-10 flex items-center gap-3 font-mono text-xs" aria-label="Steps">
        {STEPS.map((s, i) => (
          <li key={s} className="flex items-center gap-3">
            <button
              disabled={i > step || running}
              onClick={() => setStep(i as Step)}
              className={`flex items-center gap-2 ${i === step ? "text-fg" : i < step ? "text-fg-2 hover:text-fg" : "text-fg-off"}`}
            >
              <span
                className={`grid h-6 w-6 place-items-center rounded-sm border ${i === step ? "border-fg" : "border-line"}`}
              >
                {i < step ? <Icon name="check" size={12} /> : `0${i + 1}`}
              </span>
              {s}
            </button>
            {i < STEPS.length - 1 && <span className="h-px w-8 bg-line" aria-hidden />}
          </li>
        ))}
      </ol>

      {step === 0 && (
        <ModelStep
          loaded={loaded}
          busy={busy}
          error={error}
          onFile={(f) => void load(f, f.name)}
          onSample={(f, n) => void sample(f, n)}
          onReset={() => {
            setLoaded(null);
            setPin(null);
          }}
          onRemapped={(upload) => setLoaded((l) => (l ? { ...l, upload } : l))}
          onNext={() => setStep(1)}
        />
      )}
      {step === 1 && loaded && (
        <LocationStep
          city={city}
          setCity={setCity}
          pin={pin}
          setPin={setPin}
          fromModel={loaded.location}
          onBack={() => setStep(0)}
          onNext={() => setStep(2)}
        />
      )}
      {step === 2 && loaded && pin && (
        <RunStep loaded={loaded} pin={pin} running={running} error={error} onBack={() => setStep(1)} onRun={() => void run()} />
      )}
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
  const recent = recentProjects().filter((r) => r.reportId);

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
                <span className="text-fg-2">not in the model. set it in the next step</span>
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
            change model
          </button>
          <button className="btn-primary" onClick={onNext}>
            set location <Icon name="arrow" />
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
        className={`mt-6 flex cursor-pointer flex-col items-center justify-center gap-2 rounded-md border border-dashed px-6 py-12 text-center transition-colors ${
          dragging ? "border-fg bg-surface-raised" : "border-line bg-surface hover:border-line-strong"
        } ${busy ? "pointer-events-none" : ""}`}
      >
        {busy ? (
          <>
            <Spinner className="h-5 w-5 text-fg-2" />
            <p className="text-sm text-fg-2">{busy}</p>
          </>
        ) : (
          <>
            <Icon name="upload" size={20} className="text-fg-2" />
            <p className="text-sm" title="IFC2x3 / IFC4, or 2D DXF (PreDCR or your own layers) · up to 60 MB · DWG: save as DXF first">
              .ifc or .dxf
            </p>
          </>
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

      <p className="label mt-8">or select a sample</p>
      <ul className="panel divide-y divide-line-subtle">
        {SAMPLES.map((s) => (
          <li key={s.file}>
            <button
              disabled={!!busy}
              onClick={() => onSample(s.file, s.name)}
              className="group flex w-full items-center gap-4 px-4 py-3.5 text-left transition-colors hover:bg-surface-raised disabled:opacity-50"
            >
              <Icon name="cube" size={20} className="text-fg-2" />
              <span className="min-w-0 flex-1">
                <span className="block text-sm font-medium">{s.name}</span>
                <span className="block font-mono text-2xs text-fg-3" title={s.blurb}>{s.facts}</span>
              </span>
              <Icon name="arrow" className="text-fg-3 transition-colors group-hover:text-fg" />
            </button>
          </li>
        ))}
      </ul>

      {recent.length > 0 && (
        <>
          <p className="label mt-8">recent reports</p>
          <ul className="panel divide-y divide-line-subtle">
            {recent.slice(0, 5).map((r) => (
              <li key={r.id}>
                <Link
                  to={`/reports/${r.reportId}`}
                  className="flex items-center justify-between px-4 py-2.5 text-sm hover:bg-surface-raised"
                >
                  <span>{r.name}</span>
                  <span className="font-mono text-2xs text-fg-3">{new Date(r.at).toLocaleDateString()}</span>
                </Link>
              </li>
            ))}
          </ul>
        </>
      )}
    </section>
  );
}

function LocationStep({
  city,
  setCity,
  pin,
  setPin,
  fromModel,
  onBack,
  onNext,
}: {
  city: string;
  setCity: (c: string) => void;
  pin: LatLon | null;
  setPin: (p: LatLon) => void;
  fromModel: LatLon | null;
  onBack: () => void;
  onNext: () => void;
}) {
  const cities = useQuery({ queryKey: ["cities"], queryFn: api.cities, staleTime: Infinity });
  const [q, setQ] = useState("");
  const [places, setPlaces] = useState<Place[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<unknown>(null);
  const key = pin ? [pin.lat.toFixed(4), pin.lon.toFixed(4)] : null;
  const located = useQuery({
    queryKey: ["locate", key],
    queryFn: () => api.locate(pin!.lat, pin!.lon),
    enabled: !!pin,
    staleTime: Infinity,
  });
  const supported = cities.data ?? [];
  const current = supported.find((c) => c.id === city);
  const covered = located.data?.authority_id === city;
  const fromModelPin = !!pin && !!fromModel && pin.lat === fromModel.lat && pin.lon === fromModel.lon;

  useEffect(() => {
    setPlaces(null);
  }, [city]);

  async function search(e: FormEvent) {
    e.preventDefault();
    if (q.trim().length < 3) return;
    setSearching(true);
    setSearchError(null);
    try {
      const res = await api.geocode(q, city);
      setPlaces(res);
      if (res.length === 1) setPin({ lat: res[0].lat, lon: res[0].lon });
    } catch (err) {
      setSearchError(err);
    } finally {
      setSearching(false);
    }
  }

  return (
    <section>
      <Title>where is the site.</Title>

      <p className="label mt-6">city</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-4">
        {supported.map((c) => (
          <button
            key={c.id}
            onClick={() => setCity(c.id)}
            aria-pressed={city === c.id}
            className={`flex h-14 flex-col items-start justify-center rounded-sm border px-3 text-left transition-colors ${
              city === c.id ? "border-fg bg-surface-raised" : "border-line bg-surface hover:border-line-strong"
            }`}
          >
            <span className="flex w-full items-center justify-between text-sm font-medium">
              {c.city}
              {city === c.id && <Icon name="check" size={14} />}
            </span>
            <span className="font-mono text-2xs text-fg-2">{c.id.toUpperCase()} · UDCPR</span>
          </button>
        ))}
        {COMING.map((name) => (
          <button
            key={name}
            disabled
            title="Not covered yet"
            className="flex h-14 cursor-not-allowed flex-col items-start justify-center rounded-sm border border-line-subtle px-3 text-left text-fg-off"
          >
            <span className="text-sm">{name}</span>
            <span className="font-mono text-2xs">soon</span>
          </button>
        ))}
      </div>

      <p className="label mt-6">address</p>
      <form onSubmit={search} className="flex gap-2">
        <input
          className="input"
          placeholder={`street, area or landmark in ${current?.city ?? "the city"}`}
          value={q}
          onChange={(e) => setQ(e.target.value)}
        />
        <button className="btn-secondary shrink-0" disabled={searching || q.trim().length < 3}>
          {searching ? <Spinner /> : <Icon name="search" />} search
        </button>
      </form>
      {searchError ? <FieldError error={searchError} /> : null}
      {places && (
        <ul className="panel mt-2 divide-y divide-line-subtle">
          {places.length === 0 && <li className="px-3 py-2.5 text-sm text-fg-2">no match in {current?.city}. drop a pin on the map instead.</li>}
          {places.map((p) => (
            <li key={`${p.lat},${p.lon}`}>
              <button
                onClick={() => setPin({ lat: p.lat, lon: p.lon })}
                className={`flex w-full items-start gap-2.5 px-3 py-2.5 text-left text-sm hover:bg-surface-raised ${
                  pin?.lat === p.lat && pin?.lon === p.lon ? "bg-surface-raised" : ""
                }`}
              >
                <Icon name="pin" className="mt-0.5 text-fg-2" />
                <span className="min-w-0 flex-1 truncate">{p.label}</span>
              </button>
            </li>
          ))}
        </ul>
      )}

      <div className="mt-4">
        <MapPin value={pin} onChange={setPin} center={current?.center ?? undefined} />
      </div>
      <div className="mt-3 flex min-h-[20px] items-center gap-2 text-sm">
        {!pin && <span className="text-fg-3">search, or click the map</span>}
        {pin && located.isLoading && (
          <span className="flex items-center gap-2 text-fg-2">
            <Spinner /> checking the authority
          </span>
        )}
        {pin && located.data && (
          <>
            <Icon name={covered ? "check" : "x"} className={covered ? "text-fg" : "text-danger"} />
            <span>{located.data.label ?? "pinned"}</span>
            <span className="text-fg-2">·</span>
            <span className={covered ? "text-fg-2" : "text-danger"}>
              {covered ? current?.authority : located.data.note}
            </span>
            {fromModelPin && <Chip>from model</Chip>}
          </>
        )}
      </div>

      <div className="mt-8 flex justify-between">
        <button className="btn-ghost" onClick={onBack}>
          <Icon name="back" /> back
        </button>
        <button className="btn-primary" disabled={!pin || !covered} onClick={onNext}>
          continue <Icon name="arrow" />
        </button>
      </div>
    </section>
  );
}

function RunStep({
  loaded,
  pin,
  running,
  error,
  onBack,
  onRun,
}: {
  loaded: Loaded;
  pin: LatLon;
  running: boolean;
  error: unknown;
  onBack: () => void;
  onRun: () => void;
}) {
  const located = useQuery({
    queryKey: ["locate", [pin.lat.toFixed(4), pin.lon.toFixed(4)]],
    queryFn: () => api.locate(pin.lat, pin.lon),
    staleTime: Infinity,
  });
  const c = loaded.upload.counts;
  return (
    <section>
      <Title>run the check.</Title>
      <div className="panel mt-6 divide-y divide-line-subtle">
        <Row k="model" v={loaded.name} />
        <Row k="read" v={<span className="num">{c.spaces} rooms · {c.doors} doors · {c.levels} storeys</span>} />
        <Row
          k="site"
          v={
            <span>
              {located.data?.label ?? "pinned"}{" "}
              <span className="num text-fg-2">
                ({pin.lat.toFixed(5)}, {pin.lon.toFixed(5)})
              </span>
            </span>
          }
        />
        <Row k="authority" v="Pune Municipal Corporation" />
        <Row k="rulebook" v={<span className="num">UDCPR 2020 → NBC 2016 · PMC TOD layer</span>} />
      </div>
      {error ? (
        <div className="mt-4">
          <ErrorBox error={error} title="the check couldn't start" onRetry={onRun} />
        </div>
      ) : null}
      <div className="mt-8 flex justify-between">
        <button className="btn-ghost" onClick={onBack} disabled={running}>
          <Icon name="back" /> back
        </button>
        <button className="btn-primary" onClick={onRun} disabled={running}>
          {running ? <Spinner /> : null} run check
        </button>
      </div>
    </section>
  );
}

// 2D drawings: each layer's role. PreDCR layers are recognised; anything else is set here (P10.5).
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
