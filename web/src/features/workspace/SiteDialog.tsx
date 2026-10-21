import { useState, type FormEvent } from "react";
import { api, type Place } from "../../api/client";
import type { BuildingModel, Fact } from "../../api/types";
import { FieldError, Icon, Spinner } from "../../components/ui";
import SiteMap, { startPlacement, type Placement, type SiteDraft } from "../brief/SiteMap";
import PlanningFacts from "../upload/PlanningFacts";

// P12.3 inside the workspace: place the drawing, draw or type the plot, tag the sides. Saving
// writes declared brief answers and re-runs the check.

export function siteAnswers(draft: SiteDraft): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  if (!draft.placement) return out;
  out["project.location"] = { lat: draft.placement.lat, lon: draft.placement.lon };
  out["site.placement"] = draft.placement;
  if (draft.boundary) out["site.boundary"] = draft.boundary;
  const tags = Object.fromEntries(Object.entries(draft.tags).filter(([, t]) => t.kind));
  if (Object.keys(tags).length) out["site.edges"] = tags;
  return out;
}

export default function SiteDialog({
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
  const [draft, setDraft] = useState<SiteDraft>(() => {
    const saved = brief["site.placement"]?.value as Placement | undefined;
    const loc = model.project.location.value;
    const drawn = brief["site.boundary"]?.value as number[][] | undefined;
    return {
      placement: saved ?? (loc ? startPlacement(model, { lat: loc.lat, lon: loc.lon }) : null),
      // The model passed to the workspace already has a drawn plot merged in; keep editing it.
      boundary: drawn ? model.site.boundary : null,
      tags: {},
    };
  });
  const [touched, setTouched] = useState(false);
  const [facts, setFacts] = useState<Record<string, unknown>>({});
  const [q, setQ] = useState("");
  const [places, setPlaces] = useState<Place[] | null>(null);
  const [searching, setSearching] = useState(false);
  const [searchError, setSearchError] = useState<unknown>(null);
  // ~100 m steps: moving the building a little doesn't look the site up again
  const pin = draft.placement ? { lat: +draft.placement.lat.toFixed(3), lon: +draft.placement.lon.toFixed(3) } : null;

  function go(p: { lat: number; lon: number }) {
    setDraft((d) => ({ ...d, placement: d.placement ? { ...d.placement, ...p } : startPlacement(model, p) }));
    setTouched(true);
  }
  async function search(e: FormEvent) {
    e.preventDefault();
    if (q.trim().length < 3) return;
    setSearching(true);
    setSearchError(null);
    try {
      const res = await api.geocode(q, "pmc");
      setPlaces(res);
      if (res.length === 1) go(res[0]);
    } catch (err) {
      setSearchError(err);
    } finally {
      setSearching(false);
    }
  }

  return (
    <div className="fixed inset-0 z-[2000] grid place-items-center bg-black/60 p-4" role="dialog" aria-modal aria-label="Set the site">
      <div className="flex max-h-full w-full max-w-[960px] flex-col overflow-hidden rounded-md border border-line bg-canvas">
        <header className="flex items-center gap-3 border-b border-line-subtle px-5 py-3">
          <span className="h2 flex-1">set the site</span>
          <span className="hidden text-xs text-fg-3 sm:inline">click the map where it stands · drag to move · draw the plot · tag each side</span>
          <button className="btn-ghost h-7 px-1.5" onClick={onClose} aria-label="Close">
            <Icon name="x" size={14} />
          </button>
        </header>
        <div className="min-h-0 overflow-y-auto p-5">
          <form onSubmit={search} className="mb-3 flex gap-2">
            <input className="input" placeholder="address, area or landmark in Pune" value={q} onChange={(e) => setQ(e.target.value)} />
            <button className="btn-secondary shrink-0" disabled={searching || q.trim().length < 3}>
              {searching ? <Spinner /> : <Icon name="search" />} search
            </button>
          </form>
          {searchError ? <FieldError error={searchError} /> : null}
          {places && places.length !== 1 && (
            <ul className="panel mb-3 divide-y divide-line-subtle">
              {places.length === 0 && <li className="px-3 py-2 text-sm text-fg-2">no match in Pune. click the map instead.</li>}
              {places.map((p) => (
                <li key={`${p.lat},${p.lon}`}>
                  <button onClick={() => { go(p); setPlaces(null); }} className="flex w-full items-center gap-2 px-3 py-2 text-left text-sm hover:bg-surface-raised">
                    <Icon name="pin" className="text-fg-2" />
                    <span className="min-w-0 flex-1 truncate">{p.label}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
          <SiteMap
            model={model}
            draft={draft}
            onChange={(d) => {
              setDraft(d);
              setTouched(true);
            }}
            className="h-[48vh]"
          />
          {pin && (
            <div className="panel mt-3 divide-y divide-line-subtle">
              <PlanningFacts projectId={projectId} pin={pin} answers={facts} onAnswer={(path, v) => { setFacts((f) => ({ ...f, [path]: v })); setTouched(true); }} />
            </div>
          )}
        </div>
        <footer className="flex items-center justify-end gap-2 border-t border-line-subtle px-5 py-3">
          <button className="btn-ghost" onClick={onClose}>
            <Icon name="x" /> cancel
          </button>
          <button className="btn-primary" disabled={!draft.placement || !touched || busy} onClick={() => onSave({ ...facts, ...siteAnswers(draft) })}>
            {busy ? <Spinner /> : <Icon name="refresh" />} save & check
          </button>
        </footer>
      </div>
    </div>
  );
}
