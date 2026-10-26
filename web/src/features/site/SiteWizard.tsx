import { useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, type Suggest } from "../../api/client";
import type { BuildingModel, Fact } from "../../api/types";
import { Icon, Spinner, type IconName } from "../../components/ui";
import SiteMap, {
  PUNE,
  PlotSize,
  SideList,
  alignRotation,
  area,
  norm,
  sides,
  startPlacement,
  tagOf,
  toGeo,
  type Focus,
  type Placement,
  type SiteDraft,
} from "../brief/SiteMap";
import PlanningFacts from "../upload/PlanningFacts";

// Site setup, one step at a time: city → address → north → plot & sides → planning facts → check.
// Every new file opens here, 2D or 3D. What the file already says (its location, its true north,
// its plot and roads) fills the steps in and marks them "from the file", so a complete model is one
// click from its check. Saving writes declared brief answers and runs the check.

type StepId = "city" | "address" | "north" | "plot" | "planning" | "review";
type Status = "file" | "done" | "optional" | "todo";
const STEPS: { id: StepId; title: string; icon: IconName }[] = [
  { id: "city", title: "city", icon: "home" },
  { id: "address", title: "address", icon: "search" },
  { id: "north", title: "north", icon: "refresh" },
  { id: "plot", title: "plot & sides", icon: "polygon" },
  { id: "planning", title: "planning facts", icon: "book" },
  { id: "review", title: "check", icon: "check" },
];

export function siteAnswers(draft: SiteDraft, locationChanged: boolean): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (!draft.placement) return out;
  if (locationChanged) out["project.location"] = { lat: draft.placement.lat, lon: draft.placement.lon };
  out["site.placement"] = draft.placement;
  if (draft.boundary) out["site.boundary"] = draft.boundary;
  const tags = Object.fromEntries(Object.entries(draft.tags).filter(([, t]) => t.kind));
  if (Object.keys(tags).length) out["site.edges"] = tags;
  return out;
}

export default function SiteWizard({
  projectId,
  model,
  brief,
  busy,
  onClose,
  onSave,
}: {
  projectId: string;
  model: BuildingModel;
  brief: Record<string, Fact<unknown>>;
  busy: boolean;
  onClose: () => void;
  onSave: (answers: Record<string, unknown>) => void;
}) {
  const cities = useQuery({ queryKey: ["cities"], queryFn: api.cities, staleTime: Infinity });
  const north = useQuery({ queryKey: ["orientation", projectId], queryFn: () => api.orientation(projectId), staleTime: Infinity });

  const loc = model.project.location;
  const savedPlacement = brief["site.placement"]?.value as Placement | undefined;
  const [chosenCity, setAuthority] = useState<string | null>((model.project.authority_id?.value as string | null) ?? null);
  // One supported city: it is the answer.
  const authority = chosenCity ?? (cities.data?.length === 1 ? cities.data[0].id : null);
  const [draft, setDraft] = useState<SiteDraft>(() => ({
    placement: savedPlacement ?? (loc.value ? startPlacement(model, { lat: loc.value.lat, lon: loc.value.lon }) : null),
    // The model passed to the workspace already has a drawn plot merged in; keep editing it.
    boundary: brief["site.boundary"]?.value ? model.site.boundary : null,
    tags: {},
  }));
  const [locChanged, setLocChanged] = useState(!loc.value && !!savedPlacement);
  const [northFrom, setNorthFrom] = useState<"file" | "saved" | "you" | null>(savedPlacement ? "saved" : null);
  const [plotFrom, setPlotFrom] = useState<"file" | "drawn" | "typed" | null>(brief["site.boundary"] ? "drawn" : model.site.boundary ? "file" : null);
  const [tagged, setTagged] = useState(false);
  const [facts, setFacts] = useState<Record<string, unknown>>({});
  const [seenPlanning, setSeenPlanning] = useState(false);
  const [placeLabel, setPlaceLabel] = useState<string | null>(null);
  const [focus, setFocus] = useState<Focus | null>(null);
  const [selected, setSelected] = useState<string | null>(null);
  const [drawMode, setDrawMode] = useState(false);
  const [typeMode, setTypeMode] = useState(false);
  const [alignSide, setAlignSide] = useState<string | null>(null);
  const [areaHint, setAreaHint] = useState<string | null>(null);


  // North from the file turns the plan as soon as it is known (unless the user already set one).
  const fileNorth = north.data?.rotation_deg ?? null;
  useEffect(() => {
    if (fileNorth === null || northFrom) return;
    setNorthFrom("file");
    setDraft((d) => (d.placement ? { ...d, placement: { ...d.placement, rotation_deg: fileNorth } } : d));
  }, [fileNorth, northFrom]);

  const pl = draft.placement;
  const ring = draft.boundary ?? model.site.boundary ?? null;
  const edges = useMemo(() => sides(model, draft), [model, draft]);
  const roads = edges.filter((e) => tagOf(model, draft, e.id).kind === "road");
  const sidesDone = !!ring && edges.length > 0 && edges.every((e) => {
    const t = tagOf(model, draft, e.id);
    return t.kind && (t.kind !== "road" || t.road_width_m);
  });
  const ownPlot = !!model.site.boundary && !draft.boundary;

  const status: Record<StepId, Status> = {
    city: authority ? "done" : "todo",
    address: pl ? (loc.value && !locChanged ? "file" : "done") : "todo",
    north: northFrom === "file" ? "file" : northFrom ? "done" : ownPlot ? "optional" : "todo",
    plot: sidesDone ? (plotFrom === "file" && !tagged ? "file" : "done") : "todo",
    planning: seenPlanning || Object.keys(facts).length ? "done" : "optional",
    review: "optional",
  };
  // Open on the first step that still needs an answer (the check itself when none does). Until the
  // user picks a step this follows the data as it loads, so a complete file lands on the check.
  const firstOpen = (["city", "address", "north", "plot"] as StepId[]).find((s) => status[s] === "todo") ?? "review";
  const [picked, setStep] = useState<StepId | null>(null);
  const loading = cities.isLoading || north.isLoading;
  useEffect(() => {
    if (!picked && !loading) setStep(firstOpen);
  }, [picked, loading, firstOpen]);
  const step = picked ?? "city";
  const idx = STEPS.findIndex((s) => s.id === step);
  useEffect(() => {
    if ((step === "north" || step === "plot" || step === "review") && draft.placement) fitPlot(draft.placement);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [step]);
  useEffect(() => {
    if (step === "planning") setSeenPlanning(true);
    if (step !== "plot") setDrawMode(false);
    if (step !== "north") setAlignSide(null);
  }, [step]);

  // Address steps zoom: a new placement made from the list is flown to.
  const flyKey = useRef(0);
  const look = (f: Omit<Focus, "key">) => setFocus({ ...f, key: ++flyKey.current });

  // Show the whole plot (or the building), close up.
  function fitPlot(p: Placement) {
    const shape = draft.boundary ?? model.site.boundary ?? model.building.footprint;
    if (!shape?.length) return look({ lat: p.lat, lon: p.lon, zoom: 19 });
    const g = shape.map((q) => toGeo(q, p));
    const lats = g.map((x) => x[0]), lons = g.map((x) => x[1]);
    look({ lat: p.lat, lon: p.lon, extent: [Math.min(...lons), Math.min(...lats), Math.max(...lons), Math.max(...lats)], zoom: 20 });
  }
  function place(p: { lat: number; lon: number }) {
    const next = draft.placement ? { ...draft.placement, lat: p.lat, lon: p.lon } : startPlacement(model, p, fileNorth ?? 0);
    setDraft((d) => ({ ...d, placement: next }));
    setLocChanged(true);
    setAreaHint(null);
    fitPlot(next);
  }
  function setRotation(deg: number, from: "you" | "file" = "you") {
    if (!pl) return;
    setDraft((d) => ({ ...d, placement: { ...d.placement!, rotation_deg: norm(deg) } }));
    setNorthFrom(from);
  }
  function change(d: SiteDraft) {
    if (d.placement && pl && (d.placement.lat !== pl.lat || d.placement.lon !== pl.lon)) setLocChanged(true);
    if (d.placement && pl && d.placement.rotation_deg !== pl.rotation_deg) setNorthFrom("you");
    if (!pl && d.placement) setLocChanged(true);
    if (d.tags !== draft.tags) setTagged(true);
    setDraft(d);
  }

  const tool = step === "plot" && drawMode ? "draw" : step === "north" && alignSide ? "align" : step === "address" || step === "north" || step === "plot" ? "place" : "none";
  const city = cities.data?.find((c) => c.id === authority);
  const pin = pl ? { lat: +pl.lat.toFixed(3), lon: +pl.lon.toFixed(3) } : null;
  // A name for the spot, and whether it is in the chosen city at all.
  const where = useQuery({
    queryKey: ["locate", pin?.lat, pin?.lon],
    queryFn: () => api.locate(pin!.lat, pin!.lon),
    enabled: !!pin,
    staleTime: Infinity,
  });
  const address = placeLabel ?? where.data?.label ?? (pl ? `${pl.lat.toFixed(5)}, ${pl.lon.toFixed(5)}` : null);
  const outside = !!where.data && !!authority && where.data.authority_id !== authority;

  return (
    <div className="fixed inset-0 z-[2000] flex flex-col bg-canvas text-fg" role="dialog" aria-modal aria-label="Site setup">
      <header className="flex h-12 shrink-0 items-center gap-3 border-b border-line-subtle px-4">
        <Icon name="pin" />
        <span className="h2 flex-1">site setup</span>
        <span className="hidden text-xs text-fg-3 md:inline">where the building stands, which way it faces, the plot and its roads</span>
        <button className="btn-ghost h-8 px-2" onClick={onClose} aria-label="Close">
          <Icon name="x" /> close
        </button>
      </header>

      <div className="grid min-h-0 flex-1 grid-rows-[auto_1fr] lg:grid-cols-[400px_1fr] lg:grid-rows-1">
        <aside className="flex min-h-0 flex-col border-b border-line-subtle lg:border-b-0 lg:border-r">
          <ol className="flex gap-1 overflow-x-auto border-b border-line-subtle p-2 lg:flex-col lg:gap-0.5">
            {STEPS.map((s, i) => (
              <li key={s.id}>
                <button
                  onClick={() => setStep(s.id)}
                  aria-current={s.id === step}
                  className={`flex h-9 w-full shrink-0 items-center gap-2.5 whitespace-nowrap rounded-sm px-2.5 text-left text-sm ${s.id === step ? "bg-surface-raised text-fg" : "text-fg-2 hover:bg-surface hover:text-fg"}`}
                >
                  <span className="w-4 font-mono text-2xs text-fg-3">{i + 1}</span>
                  <Icon name={s.icon} size={14} />
                  <span className="flex-1">{s.title}</span>
                  {s.id !== "review" && <StatusTag s={status[s.id]} />}
                </button>
              </li>
            ))}
          </ol>

          <div className="min-h-0 flex-1 overflow-y-auto p-4">
            {step === "city" && (
              <Panel title="Which city?" lead="The city decides the rulebook and where addresses are searched.">
                {cities.isLoading && <Spinner />}
                <div className="flex flex-col gap-2">
                  {cities.data?.map((c) => (
                    <button
                      key={c.id}
                      onClick={() => {
                        setAuthority(c.id);
                        if (!pl && c.center) look({ ...c.center, zoom: 12 });
                      }}
                      aria-pressed={c.id === authority}
                      className={`flex items-center gap-3 rounded-md border px-3 py-3 text-left ${c.id === authority ? "border-fg bg-surface-raised" : "border-line-subtle hover:border-line"}`}
                    >
                      <Icon name="home" />
                      <span className="flex-1">
                        <span className="block text-sm font-medium">{c.city}</span>
                        <span className="block text-xs text-fg-2">{c.authority} · UDCPR 2020, NBC 2016 where it is silent</span>
                      </span>
                      {c.id === authority && <Icon name="check" />}
                    </button>
                  ))}
                </div>
                <p className="mt-3 text-xs text-fg-3">Only Pune is set up so far.</p>
              </Panel>
            )}

            {step === "address" && (
              <Panel title="Where is it?" lead="Type an address, a society or a landmark, then pick it. Or click the map where the building stands.">
                <AddressSearch
                  authority={authority ?? "pmc"}
                  onPick={(p) => {
                    setPlaceLabel(p.label);
                    if (p.precise) place(p);
                    else {
                      look({ lat: p.lat, lon: p.lon, extent: p.extent });
                      setAreaHint(p.label.split(",")[0]);
                    }
                  }}
                />
                {areaHint && (
                  <p className="mt-3 flex items-start gap-2 rounded-sm border border-line-subtle bg-surface px-3 py-2 text-xs text-fg-2">
                    <Icon name="info" size={14} /> Zoomed to {areaHint}. Click your plot on the map to put the building there.
                  </p>
                )}
                {pl && (
                  <div className="mt-4 rounded-md border border-line-subtle p-3 text-sm">
                    <p className="flex items-center gap-2">
                      <Icon name="pin" size={14} />
                      <span className="min-w-0 flex-1 truncate">{address}</span>
                      {status.address === "file" && <StatusTag s="file" />}
                    </p>
                    <p className="mt-1 font-mono text-2xs text-fg-3">
                      {pl.lat.toFixed(5)}° N, {pl.lon.toFixed(5)}° E
                    </p>
                    <p className="mt-2 text-xs text-fg-2">Drag the red building on the map to fine-tune it.</p>
                  </div>
                )}
                {outside && <Outside city={city?.city} />}
              </Panel>
            )}

            {step === "north" && (
              <Panel
                title="Which way does it face?"
                lead={ownPlot ? "Your file has its own plot, so this only lines the plan up with the map. You can skip it." : "Turn the plan until it sits on its plot. Then the plot you draw lines up with the drawing."}
              >
                {!pl ? (
                  <Needs onGo={() => setStep("address")}>Place the building first.</Needs>
                ) : (
                  <>
                    {fileNorth !== null && (
                      <button
                        className={`mb-3 flex w-full items-center gap-2 rounded-sm border px-3 py-2 text-left text-xs ${northFrom === "file" ? "border-fg" : "border-line-subtle text-fg-2"}`}
                        onClick={() => setRotation(fileNorth, "file")}
                      >
                        <Icon name="check" size={12} /> {north.data?.source}: {fileNorth}°
                      </button>
                    )}
                    <label className="label">angle from north</label>
                    <div className="mt-1 flex items-center gap-1">
                      <button className="btn-secondary h-9 px-2 text-xs" onClick={() => setRotation(pl.rotation_deg - 5)}>−5</button>
                      <button className="btn-secondary h-9 px-2 text-xs" onClick={() => setRotation(pl.rotation_deg - 1)}>−1</button>
                      <input
                        type="number"
                        step={0.5}
                        className="input h-9 w-24 text-center font-mono"
                        value={pl.rotation_deg}
                        onChange={(e) => setRotation(+e.target.value || 0)}
                        aria-label="angle in degrees"
                      />
                      <span className="text-sm text-fg-2">°</span>
                      <button className="btn-secondary h-9 px-2 text-xs" onClick={() => setRotation(pl.rotation_deg + 1)}>+1</button>
                      <button className="btn-secondary h-9 px-2 text-xs" onClick={() => setRotation(pl.rotation_deg + 5)}>+5</button>
                    </div>
                    <div className="mt-2 flex gap-1">
                      {[0, 90, 180, -90].map((a) => (
                        <button key={a} className={`h-7 rounded-sm border px-2 font-mono text-xs ${pl.rotation_deg === a ? "border-fg" : "border-line-subtle text-fg-2"}`} onClick={() => setRotation(a)}>
                          {a}°
                        </button>
                      ))}
                    </div>
                    <p className="mt-2 text-xs text-fg-3">Or drag the round handle on the map. Positive turns the plan anticlockwise.</p>

                    <div className="mt-5 rounded-md border border-line-subtle p-3">
                      <p className="flex items-center gap-2 text-sm font-medium">
                        <Icon name="road" size={14} /> line it up with the street
                      </p>
                      <p className="mt-1 text-xs text-fg-2">Pick the side that faces the street, then click two points along the street on the map.</p>
                      <div className="mt-2 flex items-center gap-2">
                        <select
                          className="input h-8 py-0 text-sm"
                          value={alignSide ?? ""}
                          onChange={(e) => setAlignSide(e.target.value || null)}
                          aria-label="side that faces the street"
                        >
                          <option value="">choose a side…</option>
                          {alignChoices(model, draft).map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.label}
                            </option>
                          ))}
                        </select>
                        {alignSide && (
                          <button className="btn-ghost h-8 text-xs" onClick={() => setAlignSide(null)}>
                            <Icon name="x" size={12} /> cancel
                          </button>
                        )}
                      </div>
                      {alignSide && <p className="mt-2 text-xs text-accent">Now click two points along the street on the map.</p>}
                    </div>
                  </>
                )}
              </Panel>
            )}

            {step === "plot" && (
              <Panel title="The plot and its sides" lead="The plot's sides decide the margins: say which faces a road (and how wide it is in the Development Plan) and which face neighbours.">
                {!pl ? (
                  <Needs onGo={() => setStep("address")}>Place the building first.</Needs>
                ) : (
                  <>
                    {ring && !drawMode && !typeMode && (
                      <div className="mb-3 flex items-center gap-2 rounded-md border border-line-subtle px-3 py-2 text-sm">
                        <Icon name="polygon" size={14} />
                        <span className="flex-1">
                          {edges.length} sides · {area(ring).toFixed(0)} m²
                        </span>
                        {plotFrom === "file" && <StatusTag s="file" />}
                      </div>
                    )}
                    {!drawMode && !typeMode && (
                      <div className="mb-4 grid grid-cols-2 gap-2">
                        <button className="btn-secondary h-9 text-xs" onClick={() => { setDrawMode(true); setSelected(null); }}>
                          <Icon name="polygon" size={14} /> {ring ? "draw again" : "draw on the map"}
                        </button>
                        <button className="btn-secondary h-9 text-xs" onClick={() => setTypeMode(true)} disabled={!model.building.footprint}>
                          <Icon name="ruler" size={14} /> type its size
                        </button>
                        {draft.boundary && model.site.boundary && (
                          <button className="btn-ghost col-span-2 h-8 text-xs" onClick={() => { setDraft({ ...draft, boundary: null, tags: {} }); setPlotFrom("file"); }}>
                            <Icon name="back" size={12} /> use the plot from the file
                          </button>
                        )}
                      </div>
                    )}
                    {drawMode && (
                      <div className="mb-4 rounded-md border border-accent p-3 text-xs text-fg-2">
                        <p className="text-sm text-fg">Click each corner of the plot on the map.</p>
                        <p className="mt-1">Lengths show as you go. Click the first corner to close. Backspace takes a corner back.</p>
                        <button className="btn-ghost mt-2 h-7 text-xs" onClick={() => setDrawMode(false)}>
                          <Icon name="x" size={12} /> cancel
                        </button>
                      </div>
                    )}
                    {typeMode && (
                      <div className="mb-4 rounded-md border border-line-subtle p-3">
                        <PlotSize
                          model={model}
                          onPlot={(r) => {
                            setDraft({ ...draft, boundary: r, tags: {} });
                            setPlotFrom("typed");
                            setTypeMode(false);
                          }}
                        />
                        <button className="btn-ghost mt-2 h-7 text-xs" onClick={() => setTypeMode(false)}>
                          <Icon name="x" size={12} /> cancel
                        </button>
                      </div>
                    )}
                    {ring && !drawMode && (
                      <SideList model={model} draft={draft} onChange={change} selected={selected} onSelect={setSelected} />
                    )}
                  </>
                )}
              </Panel>
            )}

            {step === "planning" && (
              <Panel title="Planning facts" lead="Suggested from the rooms and the location. Confirm them, or pick another value; dashed ones are used as suggested.">
                {pin ? (
                  <div className="panel divide-y divide-line-subtle">
                    <PlanningFacts projectId={projectId} pin={pin} answers={facts} onAnswer={(path, v) => setFacts((f) => ({ ...f, [path]: v }))} />
                  </div>
                ) : (
                  <Needs onGo={() => setStep("address")}>Place the building first.</Needs>
                )}
              </Panel>
            )}

            {step === "review" && (
              <Panel title="Ready to check" lead="Anything not set is checked as can't verify, with a question, never as a pass.">
                <dl className="divide-y divide-line-subtle rounded-md border border-line-subtle text-sm">
                  <Row k="city" s={status.city} onEdit={() => setStep("city")}>
                    {city ? `${city.city} · ${city.authority}` : "not set"}
                  </Row>
                  <Row k="address" s={outside ? "todo" : status.address} onEdit={() => setStep("address")}>
                    {address ?? "not set"}
                  </Row>
                  <Row k="north" s={status.north} onEdit={() => setStep("north")}>
                    {pl ? `${pl.rotation_deg}°` : "—"}
                  </Row>
                  <Row k="plot" s={ring ? (status.plot === "todo" ? "done" : status.plot) : "todo"} onEdit={() => setStep("plot")}>
                    {ring ? `${edges.length} sides · ${area(ring).toFixed(0)} m²` : "not set"}
                  </Row>
                  <Row k="roads" s={status.plot} onEdit={() => setStep("plot")}>
                    {roads.length ? roads.map((e) => `${e.id} ${tagOf(model, draft, e.id).road_width_m ?? "?"} m`).join(" · ") : "no road side yet"}
                  </Row>
                  <Row k="planning" s={status.planning} onEdit={() => setStep("planning")}>
                    {Object.keys(facts).length ? `${Object.keys(facts).length} confirmed` : "as suggested"}
                  </Row>
                </dl>
                {outside && <Outside city={city?.city} />}
              </Panel>
            )}
          </div>

          <footer className="flex items-center gap-2 border-t border-line-subtle p-3">
            <button className="btn-ghost h-9" disabled={idx === 0} onClick={() => setStep(STEPS[idx - 1].id)}>
              <Icon name="back" /> back
            </button>
            <span className="flex-1" />
            {step !== "review" ? (
              <button className="btn-primary h-9" onClick={() => setStep(STEPS[idx + 1].id)}>
                next <Icon name="arrow" />
              </button>
            ) : (
              <button
                className="btn-primary h-9"
                disabled={!pl || busy}
                onClick={() => onSave({ ...facts, ...siteAnswers(draft, locChanged) })}
              >
                {busy ? <Spinner /> : <Icon name="check" />} save & check
              </button>
            )}
          </footer>
        </aside>

        <div className="relative min-h-[320px] p-3">
          <SiteMap
            model={model}
            draft={draft}
            onChange={change}
            tool={tool}
            rotate={step === "north" && !alignSide}
            labels={step === "plot"}
            focus={focus}
            selected={selected}
            onSelect={setSelected}
            onAlign={(bearing) => {
              const side = alignChoices(model, draft).find((c) => c.id === alignSide);
              if (side && pl) setRotation(alignRotation(side.a, side.b, bearing, pl.rotation_deg));
              setAlignSide(null);
            }}
            onDrawn={() => {
              setDrawMode(false);
              setPlotFrom("drawn");
            }}
            center={city?.center ?? PUNE}
            className="h-full"
          />
        </div>
      </div>
    </div>
  );
}

/** Sides that can be lined up with a street: the plot's (roads first), else the building's own. */
function alignChoices(model: BuildingModel, draft: SiteDraft) {
  const plot = sides(model, draft).map((e) => {
    const t = tagOf(model, draft, e.id);
    return { ...e, label: `plot side ${e.id}${t.kind === "road" ? " (road)" : ""} · ${Math.hypot(e.b[0] - e.a[0], e.b[1] - e.a[1]).toFixed(1)} m`, road: t.kind === "road" };
  });
  if (plot.length) return plot.sort((a, b) => Number(b.road) - Number(a.road));
  const fp = model.building.footprint ?? [];
  return fp.map((a, i) => {
    const b = fp[(i + 1) % fp.length];
    return { id: `b${i + 1}`, a, b, road: false, label: `building side ${i + 1} · ${Math.hypot(b[0] - a[0], b[1] - a[1]).toFixed(1)} m` };
  });
}

function AddressSearch({ authority, onPick }: { authority: string; onPick: (p: Suggest) => void }) {
  const [q, setQ] = useState("");
  const [list, setList] = useState<Suggest[]>([]);
  const [open, setOpen] = useState(false);
  const [active, setActive] = useState(0);
  const [loading, setLoading] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const picked = useRef<string | null>(null); // the text a pick filled in: not searched again

  useEffect(() => {
    const text = q.trim();
    if (text === picked.current) return;
    if (text.length < 3) {
      setList([]);
      setNote(null);
      return;
    }
    const ctrl = new AbortController();
    const t = setTimeout(async () => {
      setLoading(true);
      try {
        const res = await api.suggest(text, authority, ctrl.signal);
        setList(res);
        setActive(0);
        setOpen(true);
        setNote(res.length ? null : "No match in this city yet. Keep typing, or click the map.");
      } catch (e) {
        if ((e as Error).name !== "AbortError") setNote("Suggestions are unavailable. Press Enter to search, or click the map.");
      } finally {
        setLoading(false);
      }
    }, 250);
    return () => {
      clearTimeout(t);
      ctrl.abort();
    };
  }, [q, authority]);

  async function enter() {
    if (list[active]) return choose(list[active]);
    // No suggestions (the service is down): one full search instead.
    try {
      const res = await api.geocode(q, authority);
      if (res[0]) choose({ ...res[0], kind: "place", precise: true, extent: null });
      else setNote("No match in this city. Click the map instead.");
    } catch {
      setNote("Address search is unavailable. Click the map instead.");
    }
  }
  function choose(p: Suggest) {
    const text = p.label.split(",").slice(0, 2).join(",");
    picked.current = text;
    setQ(text);
    setOpen(false);
    onPick(p);
  }
  function onKey(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === "ArrowDown") setActive((i) => Math.min(i + 1, list.length - 1));
    else if (e.key === "ArrowUp") setActive((i) => Math.max(i - 1, 0));
    else if (e.key === "Enter") void enter();
    else if (e.key === "Escape") setOpen(false);
    else return;
    e.preventDefault();
  }

  return (
    <div className="relative">
      <div className="relative">
        <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-3">
          <Icon name="search" size={14} />
        </span>
        <input
          className="input h-10 pl-8 pr-8"
          placeholder="e.g. FC Road, Kothrud, Magarpatta"
          value={q}
          onChange={(e) => setQ(e.target.value)}
          onFocus={() => list.length && setOpen(true)}
          onBlur={() => setTimeout(() => setOpen(false), 150)}
          onKeyDown={onKey}
          role="combobox"
          aria-expanded={open}
          aria-autocomplete="list"
          autoFocus
        />
        {loading && (
          <span className="absolute right-2.5 top-1/2 -translate-y-1/2">
            <Spinner className="h-3.5 w-3.5" />
          </span>
        )}
      </div>
      {open && list.length > 0 && (
        <ul className="absolute z-10 mt-1 max-h-72 w-full overflow-y-auto rounded-md border border-line bg-surface shadow-lg" role="listbox">
          {list.map((p, i) => (
            <li key={`${p.label}-${i}`} role="option" aria-selected={i === active}>
              <button
                onMouseDown={(e) => e.preventDefault()}
                onClick={() => choose(p)}
                onMouseEnter={() => setActive(i)}
                className={`flex w-full items-start gap-2 px-3 py-2 text-left text-sm ${i === active ? "bg-surface-raised" : ""}`}
              >
                <span className="mt-0.5 text-fg-2">
                  <Icon name={p.precise ? "pin" : "plan"} size={14} />
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{p.label.split(",")[0]}</span>
                  <span className="block truncate text-xs text-fg-3">{p.label.split(",").slice(1).join(",").trim() || p.kind}</span>
                </span>
                <span className="shrink-0 text-2xs text-fg-3">{p.precise ? "place" : "area"}</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {note && <p className="mt-2 text-xs text-fg-2">{note}</p>}
    </div>
  );
}

function Panel({ title, lead, children }: { title: string; lead: string; children: ReactNode }) {
  return (
    <section>
      <h2 className="h2">{title}</h2>
      <p className="mb-4 mt-1 text-sm text-fg-2">{lead}</p>
      {children}
    </section>
  );
}

function Outside({ city }: { city?: string }) {
  return (
    <p className="mt-3 flex items-start gap-2 rounded-sm border border-dashed border-accent px-3 py-2 text-xs text-fg-2">
      <Icon name="info" size={14} className="text-accent" />
      This spot is outside {city ?? "the chosen city"}. The check will look for that area's own rules, and most of ours won't apply.
    </p>
  );
}

function Needs({ onGo, children }: { onGo: () => void; children: ReactNode }) {
  return (
    <p className="flex items-center gap-2 rounded-md border border-line-subtle px-3 py-3 text-sm text-fg-2">
      {children}
      <button className="btn-secondary ml-auto h-7 text-xs" onClick={onGo}>
        <Icon name="search" size={12} /> address
      </button>
    </p>
  );
}

function Row({ k, s, onEdit, children }: { k: string; s: Status; onEdit: () => void; children: ReactNode }) {
  return (
    <div className="flex items-center gap-3 px-3 py-2.5">
      <dt className="w-16 shrink-0 text-xs text-fg-2">{k}</dt>
      <dd className="min-w-0 flex-1 truncate">{children}</dd>
      <StatusTag s={s} />
      <button className="btn-ghost h-7 px-1.5" onClick={onEdit} aria-label={`edit ${k}`}>
        <Icon name="edit" size={12} />
      </button>
    </div>
  );
}

function StatusTag({ s }: { s: Status }) {
  if (s === "file") return <span className="rounded-sm border border-line-subtle px-1.5 py-0.5 text-2xs text-fg-2">from the file</span>;
  if (s === "done") return <Icon name="check" size={14} className="text-success" />;
  if (s === "optional") return <span className="text-2xs text-fg-3">optional</span>;
  return <span className="rounded-sm border border-dashed border-accent px-1.5 py-0.5 text-2xs text-accent">to do</span>;
}
