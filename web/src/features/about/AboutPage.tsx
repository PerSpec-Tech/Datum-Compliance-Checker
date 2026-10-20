import { useQuery } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ErrorBox, Skeleton, Title } from "../../components/ui";

const ROLES: [string, string, string][] = [
  ["fast", "Nemotron Nano", "classifies unnamed rooms, triages search results, words questions"],
  ["agent", "Nemotron Super", "compiles clauses into rules, words results"],
  ["reviewer", "Nemotron Ultra", "reviews compiled rules against the clause text"],
];

const STEPS: [string, string][] = [
  ["one building format", "The Revit add-in and the IFC reader produce the same model JSON. Every fact records where it came from: model, inferred, declared or default."],
  ["authority and overlays", "The site location picks the planning authority (Pune: UDCPR 2020, NBC 2016 as fallback) and the metro TOD zone from OpenStreetMap stations."],
  ["deterministic rules", "Each rule is a clause excerpt plus short expressions. A sandboxed evaluator decides pass, fail or can't verify. No language model decides compliance."],
  ["agents around the engine", "Nemotron on Nebius Token Factory classifies rooms, compiles clauses into draft rules with a reviewer model, and words results. Tavily searches government sites for newer notifications during each check."],
  ["results back in the model", "In Revit, issues colour the elements on a dedicated 3D view. For IFC, the web viewer and a BCF export."],
];

// P7.4: how it works + live usage counters (LLM calls by role, Tavily searches). Dashboard layout.
export default function AboutPage() {
  const usage = useQuery({ queryKey: ["usage"], queryFn: api.usage, refetchInterval: 15_000 });
  const health = useQuery({ queryKey: ["health"], queryFn: api.health });
  const calls = usage.data?.models.reduce((n, m) => n + m.calls, 0) ?? 0;
  const tokens = usage.data?.models.reduce((n, m) => n + m.prompt_tokens + m.completion_tokens, 0) ?? 0;
  const searches = usage.data?.search.reduce((n, s) => n + s.calls, 0) ?? 0;

  return (
    <div className="space-y-10">
      <header className="border-b border-line-subtle pb-5">
        <Title>usage and about.</Title>
        <p className="mt-2 text-sm text-fg-2">Live counters from this server. Refreshed every 15 seconds.</p>
      </header>

      <section className="grid grid-cols-2 gap-px overflow-hidden rounded-md border border-line-subtle bg-line-subtle lg:grid-cols-4">
        <Tile label="model calls" value={calls.toLocaleString()} />
        <Tile label="tokens" value={tokens.toLocaleString()} />
        <Tile label="Tavily searches" value={searches.toLocaleString()} />
        <Tile label="rules loaded" value={health.data ? String(health.data.rules) : "—"} />
      </section>

      <section>
        <h2 className="h1">Nemotron on Token Factory</h2>
        {usage.isLoading && <Skeleton rows={3} />}
        {usage.error ? <ErrorBox error={usage.error} title="couldn't load usage" onRetry={() => void usage.refetch()} /> : null}
        <div className="panel mt-3 overflow-x-auto">
          <table className="w-full text-sm">
            <thead className="text-left text-xs text-fg-2">
              <tr className="border-b border-line-subtle">
                <th className="px-4 py-2 font-normal">role</th>
                <th className="px-4 py-2 font-normal">model</th>
                <th className="px-4 py-2 font-normal">used for</th>
                <th className="px-4 py-2 text-right font-normal">calls</th>
                <th className="px-4 py-2 text-right font-normal">tokens in / out</th>
                <th className="px-4 py-2 text-right font-normal">avg latency</th>
              </tr>
            </thead>
            <tbody>
              {ROLES.map(([role, name, what]) => {
                const rows = usage.data?.models.filter((m) => m.role === role) ?? [];
                const sum = (k: "calls" | "ok_calls" | "prompt_tokens" | "completion_tokens") => rows.reduce((n, m) => n + m[k], 0);
                const lat = rows.length ? Math.round(rows.reduce((n, m) => n + m.avg_latency_ms * m.calls, 0) / Math.max(1, sum("calls"))) : null;
                return (
                  <tr key={role} className="border-b border-line-subtle last:border-0 hover:bg-surface-raised">
                    <td className="px-4 py-2.5 font-mono text-xs text-fg-2">{role}</td>
                    <td className="px-4 py-2.5">
                      {name}
                      {rows[0] && <span className="block font-mono text-2xs text-fg-3">{rows[0].model}</span>}
                    </td>
                    <td className="px-4 py-2.5 text-fg-2">{what}</td>
                    <td className="num px-4 py-2.5 text-right">
                      {sum("calls")}
                      {sum("ok_calls") < sum("calls") && <span className="text-danger"> ({sum("calls") - sum("ok_calls")} failed)</span>}
                    </td>
                    <td className="num px-4 py-2.5 text-right">
                      {sum("prompt_tokens").toLocaleString()} / {sum("completion_tokens").toLocaleString()}
                    </td>
                    <td className="num px-4 py-2.5 text-right">{lat === null ? "—" : `${(lat / 1000).toFixed(1)} s`}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
        {usage.data && usage.data.search.length > 0 && (
          <p className="num mt-3 text-fg-2">
            Tavily ·{" "}
            {usage.data.search.map((s) => `${s.kind} ${s.calls} (${s.live_calls} live)`).join(" · ")} · results cached 7 days
          </p>
        )}
      </section>

      <section>
        <h2 className="h1">how it works</h2>
        <ol className="panel mt-3 divide-y divide-line-subtle">
          {STEPS.map(([t, d], i) => (
            <li key={t} className="grid grid-cols-[40px_200px_minmax(0,1fr)] gap-4 px-4 py-3 text-sm max-md:grid-cols-[40px_minmax(0,1fr)]">
              <span className="num text-fg-3">{String(i + 1).padStart(2, "0")}</span>
              <span className="font-medium">{t}</span>
              <span className="text-fg-2 max-md:col-start-2">{d}</span>
            </li>
          ))}
        </ol>
        {health.data && <p className="num mt-3 text-fg-3">ruleset {health.data.ruleset_version}</p>}
        <p className="meta mt-3">
          Map data and tiles © OpenStreetMap contributors. IFC handling by IfcOpenShell. A design aid: it does not
          replace professional review, AutoDCR scrutiny or approval by the planning authority.
        </p>
      </section>
    </div>
  );
}

function Tile({ label, value }: { label: string; value: string }) {
  return (
    <div className="bg-surface px-5 py-4">
      <p className="font-mono text-[22px] font-medium leading-7 tabular-nums">{value}</p>
      <p className="meta mt-1">{label}</p>
    </div>
  );
}
