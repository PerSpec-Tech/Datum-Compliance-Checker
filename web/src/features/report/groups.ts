import type { BuildingModel, Result, Status } from "../../api/types";

// Results grouped by the element they are about, worst first. Shared by the report and the workspace.

export const RANK: Record<Status, number> = { fail: 0, unverifiable: 1, advisory: 2, pass: 3, not_applicable: 4 };
export const KIND_LABEL: Record<string, string> = {
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

export interface Group {
  key: string;
  kind: string;
  id: string | null;
  name: string;
  detail: string;
  guid: string | null;
  results: Result[];
  worst: Status;
}

// Readable names for the elements a result refers to, from the model the report was run on.
export function describe(model: BuildingModel | undefined, r: Result): { name: string; detail: string } {
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

export function groupResults(results: Result[], model: BuildingModel | undefined, statuses: Set<Status>): Group[] {
  const byKey = new Map<string, Group>();
  for (const r of results) {
    if (!statuses.has(r.status)) continue;
    const kind = r.element?.kind ?? "building";
    const key = `${kind}:${r.element?.id ?? ""}`;
    let g = byKey.get(key);
    if (!g) {
      g = { key, kind, id: r.element?.id ?? null, ...describe(model, r), guid: r.element?.source_id ?? null, results: [], worst: r.status };
      byKey.set(key, g);
    }
    g.results.push(r);
    if (RANK[r.status] < RANK[g.worst]) g.worst = r.status;
  }
  const out = [...byKey.values()];
  out.forEach((g) => g.results.sort((a, b) => RANK[a.status] - RANK[b.status]));
  const fails = (g: Group) => g.results.filter((r) => r.status === "fail").length;
  return out.sort((a, b) => RANK[a.worst] - RANK[b.worst] || fails(b) - fails(a) || a.name.localeCompare(b.name));
}

/** Worst status per key (an element id, or an IFC GlobalId), over the statuses shown. */
export function worstBy(results: Result[], key: (r: Result) => string | null | undefined, statuses?: Set<Status>): Map<string, Status> {
  const m = new Map<string, Status>();
  for (const r of results) {
    const k = key(r);
    if (!k || r.status === "not_applicable" || (statuses && !statuses.has(r.status))) continue;
    const prev = m.get(k);
    if (!prev || RANK[r.status] < RANK[prev]) m.set(k, r.status);
  }
  return m;
}

/** Rooms on one floor that fail in the same way (a whole storey built too low), shown as one entry. */
export interface Bunch {
  key: string;
  floor: string;
  title: string;
  worst: Status;
  members: Group[];
}

export const isBunch = (x: Group | Bunch): x is Bunch => "members" in x;

// Minimum-height rules differ by room use (habitable, kitchen, shop…) but share one cause: a low storey.
const topic = (ruleId: string) => (/height-min$/.test(ruleId) ? "height-min" : ruleId);

/** Groups in order, with rooms that fail the same way on the same floor (at least `min`) folded into a bunch. */
export function bunchGroups(groups: Group[], min = 3): (Group | Bunch)[] {
  const sig = (g: Group) =>
    g.kind === "spaces"
      ? `${g.detail}|${[...new Set(g.results.filter((r) => r.status === "fail" || r.status === "unverifiable").map((r) => `${topic(r.rule_id)}:${r.status}`))].sort().join(",")}`
      : null;
  const bunches = new Map<string, Group[]>();
  for (const g of groups) {
    const s = sig(g);
    if (s) bunches.set(s, [...(bunches.get(s) ?? []), g]);
  }
  const out: (Group | Bunch)[] = [];
  const done = new Set<string>();
  for (const g of groups) {
    const s = sig(g);
    const members = s ? bunches.get(s)! : [];
    if (!s || members.length < min) {
      out.push(g);
    } else if (!done.has(s)) {
      done.add(s);
      const first = g.results.find((r) => r.status === g.worst) ?? g.results[0];
      const title = first && topic(first.rule_id) === "height-min" ? "clear height below the minimum" : first?.title ?? "same issue";
      out.push({ key: `bunch:${s}`, floor: g.detail, title, worst: g.worst, members });
    }
  }
  return out;
}
