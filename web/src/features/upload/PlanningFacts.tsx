import { useQuery } from "@tanstack/react-query";
import { api, type Suggestion } from "../../api/client";
import { Chip, Icon, Spinner } from "../../components/ui";

// Planning facts the checker suggests from the rooms and the pin. Suggestions are dashed
// and used as they are; choosing a value makes it yours (declared). Model values are shown plain.

type Option = { label: string; value: unknown };
const OPTIONS: Record<string, Option[]> = {
  "project.building_type": [
    { label: "bungalow (own use)", value: "bungalow_self_use" },
    { label: "apartments", value: "standalone" },
    { label: "group housing", value: "group_housing" },
    { label: "mixed use", value: "mixed_use" },
    { label: "other", value: "other" },
  ],
  "project.occupancy": [
    { label: "A-2 · 1–2 family dwelling", value: { group: "A", subdivision: "A-2" } },
    { label: "A-4 · apartment houses", value: { group: "A", subdivision: "A-4" } },
    { label: "E · business", value: { group: "E", subdivision: null } },
    { label: "F · mercantile", value: { group: "F", subdivision: null } },
  ],
  "project.congested_area": [
    { label: "congested area", value: true },
    { label: "not congested", value: false },
  ],
};
const LABEL: Record<string, string> = {
  "project.building_type": "type",
  "project.occupancy": "occupancy",
  "project.congested_area": "area",
  "project.zone": "land use",
};

const key = (v: unknown) => JSON.stringify(v);

export default function PlanningFacts({
  projectId,
  pin,
  answers,
  onAnswer,
}: {
  projectId: string;
  pin: { lat: number; lon: number };
  answers: Record<string, unknown>;
  onAnswer: (path: string, value: unknown) => void;
}) {
  const q = useQuery({
    queryKey: ["suggestions", projectId, pin.lat.toFixed(4), pin.lon.toFixed(4)],
    queryFn: () => api.suggestions(projectId, pin.lat, pin.lon),
    staleTime: Infinity,
  });
  if (q.isLoading)
    return (
      <div className="flex items-center gap-2 px-4 py-2.5 text-xs text-fg-2">
        <Spinner className="h-3 w-3" /> reading the site and the rooms…
      </div>
    );
  if (!q.data?.length) return null;
  return (
    <>
      {q.data.map((s) => (
        <FactRow key={s.path} s={s} answer={answers[s.path]} onAnswer={(v) => onAnswer(s.path, v)} />
      ))}
    </>
  );
}

function FactRow({ s, answer, onAnswer }: { s: Suggestion; answer: unknown; onAnswer: (v: unknown) => void }) {
  const fixed = s.current.source === "model" || s.current.source === "declared";
  const fact = fixed ? s.current : s.suggested;
  const value = answer !== undefined ? answer : fact.value;
  const opts = OPTIONS[s.path];
  const mine = answer !== undefined || fixed;
  const note = fixed ? (s.current.source === "model" ? "from the model" : "your answer") : s.suggested.note;
  return (
    <div className="flex items-baseline gap-4 px-4 py-2.5 text-sm">
      <span className="w-20 shrink-0 text-xs text-fg-2">{LABEL[s.path] ?? s.path}</span>
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-2">
          {opts && !fixed ? (
            <select
              className={`input h-7 w-auto py-0 text-sm ${mine ? "" : "border-dashed"}`}
              value={key(value)}
              onChange={(e) => onAnswer(JSON.parse(e.target.value))}
              title="Suggested; pick a value to confirm it"
            >
              {opts.map((o) => (
                <option key={o.label} value={key(o.value)}>
                  {o.label}
                </option>
              ))}
            </select>
          ) : (
            <span>{opts?.find((o) => key(o.value) === key(value))?.label ?? String(value)}</span>
          )}
          {!mine && (
            <button className="flex items-center gap-1 text-xs text-fg-2 hover:text-fg" onClick={() => onAnswer(value)}>
              <Icon name="check" size={12} /> confirm
            </button>
          )}
          {!mine && <Chip predicted>suggested</Chip>}
        </span>
        {note && !mine ? <span className="mt-1 block text-xs text-fg-2">{note}</span> : null}
      </span>
    </div>
  );
}
