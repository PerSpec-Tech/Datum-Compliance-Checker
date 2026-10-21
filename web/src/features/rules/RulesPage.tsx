import { useEffect, useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Link, useNavigate, useParams } from "react-router-dom";
import { api, type CompileResult, type RuleSummary } from "../../api/client";
import { Chip, ErrorBox, Icon, Skeleton, Spinner, Title } from "../../components/ui";

const RULESETS: Record<string, string> = {
  udcpr2020: "UDCPR 2020 (Maharashtra)",
  nbc2016: "NBC 2016",
  pmc: "Pune (PMC) layer",
  drafts: "compiler drafts",
};

// P6.9: bylaws compiled into code. Explorer layout: rule list, then the selected rule and the compiler.
export default function RulesPage() {
  const { ruleId } = useParams();
  const navigate = useNavigate();
  const rules = useQuery({ queryKey: ["rules"], queryFn: api.rules });
  const [filter, setFilter] = useState("");
  const [ruleset, setRuleset] = useState("all");

  const list = useMemo(
    () =>
      (rules.data ?? []).filter(
        (r) =>
          (ruleset === "all" || r.ruleset === ruleset) &&
          (!filter || `${r.id} ${r.title} ${r.clause.ref}`.toLowerCase().includes(filter.toLowerCase())),
      ),
    [rules.data, filter, ruleset],
  );
  const sets = [...new Set((rules.data ?? []).map((r) => r.ruleset))];

  return (
    <div className="space-y-6">
      <header className="border-b border-line-subtle pb-5">
        <Title>rules.</Title>

      </header>

      <div className="grid gap-6 lg:grid-cols-[320px_minmax(0,1fr)]">
        <aside className="space-y-2">
          <div className="relative">
            <Icon name="search" className="pointer-events-none absolute left-3 top-2.5 text-fg-3" />
            <input className="input pl-9" placeholder="filter rules" value={filter} onChange={(e) => setFilter(e.target.value)} />
          </div>
          <select className="input" value={ruleset} onChange={(e) => setRuleset(e.target.value)}>
            <option value="all">all rulesets ({rules.data?.length ?? 0})</option>
            {sets.map((s) => (
              <option key={s} value={s}>
                {RULESETS[s] ?? s}
              </option>
            ))}
          </select>
          {rules.isLoading && <Skeleton rows={6} />}
          {rules.error ? <ErrorBox error={rules.error} title="couldn't load the rules" onRetry={() => void rules.refetch()} /> : null}
          <ul className="panel max-h-[70vh] divide-y divide-line-subtle overflow-y-auto">
            {list.map((r) => (
              <li key={r.id}>
                <Link
                  to={`/rules/${encodeURIComponent(r.id)}`}
                  className={`relative block px-4 py-2.5 transition-colors hover:bg-surface-raised ${r.id === ruleId ? "bg-surface-raised" : ""}`}
                >
                  {r.id === ruleId && <span className="absolute inset-y-2 left-0 w-[2px] bg-fg" aria-hidden />}
                  <span className="block text-sm leading-5">{r.title}</span>
                  <span className="mt-1 flex flex-wrap items-center gap-1.5">
                    <span className="font-mono text-2xs text-fg-3">{r.clause.ref}</span>
                    <StatusChip r={r} />
                    {r.kind === "advisory" && <Chip>advisory</Chip>}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </aside>

        <div className="space-y-6">
          {ruleId ? (
            <RuleDetail id={ruleId} onClose={() => navigate("/rules")} />
          ) : (
            <div className="panel flex items-center gap-3 p-5 text-sm text-fg-2">
              <Icon name="list" /> select a rule
            </div>
          )}
          <CompileBox />
        </div>
      </div>
    </div>
  );
}

function StatusChip({ r }: { r: Pick<RuleSummary, "status"> }) {
  return r.status === "verified" ? (
    <Chip title="Checked against the source by a person">verified</Chip>
  ) : (
    <Chip predicted title="Compiled from the clause text; not yet verified by a person">
      draft
    </Chip>
  );
}

function RuleDetail({ id, onClose }: { id: string; onClose: () => void }) {
  const q = useQuery({ queryKey: ["rule", id], queryFn: () => api.rule(id) });
  if (q.isLoading) return <Skeleton rows={5} />;
  if (q.error || !q.data) return <ErrorBox error={q.error ?? "Rule not found."} title="couldn't load the rule" />;
  const r = q.data;
  return (
    <section className="panel p-5">
      <div className="flex items-start justify-between gap-4">
        <div>
          <p className="font-mono text-2xs text-fg-3">{r.id}</p>
          <h2 className="h1 mt-1">{r.title}</h2>
          <div className="mt-2 flex flex-wrap gap-1.5">
            <StatusChip r={r} />
            <Chip>{r.severity}</Chip>
            <Chip>compiled by {r.compiled_by}</Chip>
            {r.freshness && <Chip>freshness: {r.freshness.status.replace(/_/g, " ")}</Chip>}
          </div>
        </div>
        <button onClick={onClose} className="btn-ghost" aria-label="Close">
          <Icon name="x" />
        </button>
      </div>

      <blockquote className="mt-5 border-l border-fg-2 pl-3 text-sm">
        <p className="whitespace-pre-line">“{r.clause.excerpt}”</p>
        <p className="meta mt-1 font-mono">
          {r.clause.ref} · {r.clause.source}
        </p>
      </blockquote>

      <div className="mt-5 space-y-3">
        {r.for_each && <Expr label="for each" code={r.for_each} />}
        {(["applies_when", "measured", "limit", "check"] as const).map((k) =>
          r.expressions[k] ? <Expr key={k} label={k.replace("_", " ")} code={r.expressions[k]!} /> : null,
        )}
      </div>

      {r.requires.length > 0 && (
        <p className="mt-4 text-xs text-fg-3">
          reads <span className="font-mono text-fg-2">{r.requires.join(", ")}</span>
        </p>
      )}
      {Object.keys(r.tables).length > 0 && (
        <details className="mt-4">
          <summary className="cursor-pointer text-sm text-fg-2 hover:text-fg">lookup tables</summary>
          <pre className="code mt-2 max-h-80 overflow-auto">{JSON.stringify(r.tables, null, 2)}</pre>
        </details>
      )}
    </section>
  );
}

function Expr({ label, code }: { label: string; code: string }) {
  return (
    <div>
      <p className="label">{label}</p>
      <pre className="code overflow-x-auto whitespace-pre-wrap">{code}</pre>
    </div>
  );
}

// Copied verbatim from fixtures/clauses/udcpr-9.29.1-wet-door.txt (UDCPR 2020, p.165).
const EXAMPLE = {
  ref: "9.29.1 (ii)",
  source: "udcpr2020 p.165",
  text:
    "9.29.1 Doorways\nii) No exit doorway shall be less than 90 cm. in width except assembly buildings where door " +
    "width shall be not less than 200 cm. Doorway shall be not less than 200 cm. in height. Doorways for the " +
    "bathrooms, water-closets or stores shall be not less than 75 cm. wide.",
};

function CompileBox() {
  const [text, setText] = useState("");
  const [ref, setRef] = useState("");
  const [source, setSource] = useState("pasted by user");
  const [review, setReview] = useState(true);
  const [elapsed, setElapsed] = useState(0);
  const m = useMutation({
    mutationFn: () => api.compile({ clause_text: text, clause_ref: ref, source, authority: "udcpr2020", review }),
  });

  useEffect(() => {
    if (!m.isPending) return;
    const t0 = Date.now();
    setElapsed(0);
    const t = setInterval(() => setElapsed(Math.round((Date.now() - t0) / 1000)), 1000);
    return () => clearInterval(t);
  }, [m.isPending]);

  return (
    <section className="panel p-5">
      <Title as="h2" className="h1">
        compile a clause.
      </Title>

      <div className="mt-4 grid gap-3 sm:grid-cols-[10rem_minmax(0,1fr)]">
        <label>
          <span className="label">clause ref</span>
          <input className="input font-mono" value={ref} onChange={(e) => setRef(e.target.value)} placeholder="9.29.1 (ii)" />
        </label>
        <label>
          <span className="label">source</span>
          <input className="input" value={source} onChange={(e) => setSource(e.target.value)} />
        </label>
      </div>
      <label className="mt-3 block">
        <span className="label">clause text</span>
        <textarea className="input min-h-[8rem] font-mono text-xs" value={text} onChange={(e) => setText(e.target.value)} />
      </label>
      <div className="mt-3 flex flex-wrap items-center gap-4">
        <button className="btn-primary" disabled={m.isPending || text.trim().length < 20 || !ref.trim()} onClick={() => m.mutate()}>
          {m.isPending ? (
            <>
              <Spinner /> compiling <span className="font-mono">{elapsed}s</span>
            </>
          ) : (
            <>
              <Icon name="wand" /> compile
            </>
          )}
        </button>
        <label className="flex items-center gap-2 text-sm text-fg-2">
          <input type="checkbox" className="accent-[#f2f2f3]" checked={review} onChange={(e) => setReview(e.target.checked)} /> Ultra review
        </label>
        {!text && (
          <button
            className="btn-ghost"
            onClick={() => {
              setText(EXAMPLE.text);
              setRef(EXAMPLE.ref);
              setSource(EXAMPLE.source);
            }}
          >
            <Icon name="edit" /> use a UDCPR example
          </button>
        )}
      </div>
      {m.error ? (
        <div className="mt-4">
          <ErrorBox error={m.error} title="the compiler couldn't finish" onRetry={() => m.mutate()} />
        </div>
      ) : null}
      {m.data && <CompileOutput res={m.data} />}
    </section>
  );
}

function CompileOutput({ res }: { res: CompileResult }) {
  const verdict = res.review?.verdict;
  return (
    <div className="mt-5 space-y-4 border-t border-line-subtle pt-5">
      <div className="flex flex-wrap items-center gap-3 text-sm">
        <span className={`flex items-center gap-1.5 ${res.ok ? "" : "text-danger"}`}>
          <Icon name={res.ok ? "check" : "x"} size={14} />
          {res.ok ? "passed every check" : "failed checks"}
        </span>
        <span className="num text-fg-2">
          {res.attempts} attempt{res.attempts === 1 ? "" : "s"}
        </span>
        {verdict && <Chip predicted>Ultra review: {verdict}</Chip>}
      </div>
      {res.errors.length > 0 && (
        <ul className="space-y-1 text-sm text-danger">
          {res.errors.map((e) => (
            <li key={e}>{e}</li>
          ))}
        </ul>
      )}
      {res.review?.issues && res.review.issues.length > 0 && (
        <div>
          <p className="label">reviewer notes</p>
          <ul className="space-y-1 text-sm text-fg-2">
            {res.review.issues.map((i) => (
              <li key={String(i)}>— {typeof i === "string" ? i : JSON.stringify(i)}</li>
            ))}
          </ul>
        </div>
      )}
      {res.notes.length > 0 && (
        <ul className="space-y-0.5 text-xs text-fg-3">
          {res.notes.map((n) => (
            <li key={n}>{n}</li>
          ))}
        </ul>
      )}
      {res.rule && (
        <div>
          <p className="label">draft rule (generated)</p>
          <pre className="code max-h-[28rem] overflow-auto border-dashed">{JSON.stringify(res.rule, null, 2)}</pre>
        </div>
      )}
      {res.dry_run != null && (
        <details>
          <summary className="cursor-pointer text-sm text-fg-2 hover:text-fg">dry run on sample buildings</summary>
          <pre className="code mt-2 max-h-80 overflow-auto">{JSON.stringify(res.dry_run, null, 2)}</pre>
        </details>
      )}
    </div>
  );
}
