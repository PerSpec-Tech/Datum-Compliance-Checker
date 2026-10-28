import { useState } from "react";
import type { BuildingModel, CheckReport, Question, Result } from "../../api/types";
import { Icon, StatusMark, Spinner, fmt } from "../../components/ui";
import { OCCUPANCY, RESIDENTIAL_SUB, Scalar, getPath } from "../brief/BriefPage";
import { KIND_LABEL, type Group } from "../report/groups";

// the small card that opens at an element. What it is, each clause with measured vs required
// and what to change; "can't verify" results ask for the missing fact right here.

// The question that asks for a concrete missing path (questions use [*] for "every element").
function questionFor(path: string, report: CheckReport): Question | undefined {
  return report.questions.find((q) => {
    if (q.path === path) return true;
    if (!q.path.includes("[*]")) return false;
    const re = new RegExp("^" + q.path.replace(/[.]/g, "\\.").replace("[*]", "\\[[^\\]]+\\]") + "$");
    return re.test(path);
  });
}

// Facts that need the map or a drawing change, not a typed answer.
const SITE_PATHS = /^(project\.location|site\.boundary|site\.edges)/;

// Only facts ({value, source}) can be answered; measured values have to change in the model.
function isFact(model: BuildingModel | undefined, path: string): boolean {
  let node: unknown = model;
  for (const part of path.split(".")) {
    const m = /^([A-Za-z_]\w*)(?:\[([^\]]+)\])?$/.exec(part);
    if (!m || typeof node !== "object" || node === null) return false;
    node = (node as Record<string, unknown>)[m[1]];
    if (m[2] !== undefined) node = (node as { id: string }[] | undefined)?.find((e) => e.id === m[2]);
  }
  return !!node && typeof node === "object" && "source" in node && "value" in node;
}

export default function IssueCard({
  group,
  report,
  model,
  onClose,
  onAnswer,
  onSetSite,
  busy,
}: {
  group: Group;
  report: CheckReport;
  model: BuildingModel | undefined;
  onClose: () => void;
  onAnswer: (answers: Record<string, unknown>) => void;
  onSetSite: () => void;
  busy: boolean;
}) {
  const missing = [...new Set(group.results.filter((r) => r.status === "unverifiable").flatMap((r) => r.missing_inputs))];
  const typed = missing.filter((p) => !SITE_PATHS.test(p) && isFact(model, p));
  const needsSite = missing.some((p) => SITE_PATHS.test(p));
  const inModel = missing.filter((p) => !SITE_PATHS.test(p) && !isFact(model, p));
  const [answers, setAnswers] = useState<Record<string, unknown>>({});
  const ready = typed.length > 0 && typed.every((p) => answers[p] !== undefined && answers[p] !== "");

  return (
    <div className="flex max-h-full flex-col overflow-hidden rounded-md border border-line bg-surface-overlay shadow-[0_8px_24px_rgba(0,0,0,0.45)]">
      <header className="flex items-start gap-3 border-b border-line-subtle px-4 py-3">
        <span className="min-w-0 flex-1">
          <span className="h2 block truncate">{group.name}</span>
          <span className="text-xs text-fg-3">
            {KIND_LABEL[group.kind] ?? group.kind}
            {group.detail ? ` · ${group.detail}` : ""}
          </span>
        </span>
        <button className="btn-ghost h-7 px-1.5" onClick={onClose} aria-label="Close">
          <Icon name="x" size={14} />
        </button>
      </header>

      <ul className="min-h-0 flex-1 divide-y divide-line-subtle overflow-y-auto">
        {group.results.map((r) => (
          <ResultLine key={`${r.rule_id}:${r.element?.id ?? ""}`} r={r} />
        ))}
      </ul>

      {inModel.length > 0 && (
        <p className="border-t border-line-subtle bg-surface px-4 py-3 text-xs text-fg-2">
          <Icon name="info" size={12} className="mr-1.5 inline align-[-2px]" />
          Measured from the {model?.meta.source_kind === "dxf" ? "drawing" : "model"}: add{" "}
          {inModel.map((p) => p.split(".").pop()!.replace(/_m$/, "").replace(/_/g, " ")).filter((v, i, a) => a.indexOf(v) === i).join(", ")}{" "}
          there and upload again.
        </p>
      )}
      {(typed.length > 0 || needsSite) && (
        <form
          className="space-y-3 border-t border-line-subtle bg-surface px-4 py-3"
          onSubmit={(e) => {
            e.preventDefault();
            if (ready) onAnswer(answers);
          }}
        >
          {typed.map((p) => {
            const q = questionFor(p, report);
            const current = answers[p] ?? (model ? getPath(model, p) : undefined);
            return (
              <label key={p} className="block">
                <span className="mb-1 block text-xs text-fg-2">{q?.prompt ?? p}</span>
                {p === "project.occupancy" ? (
                  <select
                    className="input"
                    value={answers[p] ? JSON.stringify(answers[p]) : ""}
                    onChange={(e) => setAnswers({ ...answers, [p]: e.target.value ? JSON.parse(e.target.value) : undefined })}
                  >
                    <option value="">Choose…</option>
                    {Object.entries(RESIDENTIAL_SUB).map(([k, l]) => (
                      <option key={k} value={JSON.stringify({ group: "A", subdivision: k })}>
                        {l}
                      </option>
                    ))}
                    {Object.entries(OCCUPANCY)
                      .filter(([k]) => k !== "A")
                      .map(([k, l]) => (
                        <option key={k} value={JSON.stringify({ group: k, subdivision: null })}>
                          {l}
                        </option>
                      ))}
                  </select>
                ) : (
                  <Scalar
                    type={q?.input_type ?? "text"}
                    options={q?.options ?? null}
                    value={answers[p] ?? current}
                    onChange={(v) => setAnswers({ ...answers, [p]: v })}
                  />
                )}
              </label>
            );
          })}
          <div className="flex flex-wrap items-center gap-2">
            {typed.length > 0 && (
              <button className="btn-primary h-8" disabled={!ready || busy}>
                {busy ? <Spinner /> : <Icon name="refresh" />} answer & re-check
              </button>
            )}
            {needsSite && (
              <button type="button" className={typed.length ? "btn-secondary h-8" : "btn-primary h-8"} onClick={onSetSite}>
                <Icon name="pin" /> set the site
              </button>
            )}
          </div>
        </form>
      )}
    </div>
  );
}

function ResultLine({ r }: { r: Result }) {
  const [open, setOpen] = useState(false);
  const shown = (r.measured !== null || r.limit !== null) && r.status !== "not_applicable";
  return (
    <li>
      <button className="flex w-full items-start gap-3 px-4 py-2.5 text-left hover:bg-surface-raised" onClick={() => setOpen((o) => !o)} aria-expanded={open}>
        <span className="pt-0.5">
          <StatusMark status={r.status} short />
        </span>
        <span className="min-w-0 flex-1">
          <span className="block text-sm leading-5">{r.title}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-fg-3">
            <span className="font-mono" title={r.clause.source}>
              {r.clause.ref}
            </span>
          </span>
        </span>
        {shown && (
          <span className="shrink-0 text-right">
            <span className="num block text-sm">
              {fmt(r.measured)}
              <span className="text-fg-3"> / {fmt(r.limit)}</span>
            </span>
            {r.fix_by && (
              <span className={`block font-mono text-2xs ${r.status === "fail" ? "text-danger" : "text-fg-2"}`}>
                {r.fix_by.direction === "increase" ? "+" : "−"}
                {fmt(r.fix_by.amount)}
                {r.fix_by.unit ? ` ${r.fix_by.unit}` : ""}
              </span>
            )}
          </span>
        )}
      </button>
      {open && (
        <div className="space-y-2 bg-surface-low px-4 pb-3 pt-1 text-xs">
          <p className="text-fg-2">{r.message}</p>
          <blockquote className="border-l border-fg-2 pl-3 text-fg">
            <p className="whitespace-pre-line">“{r.clause.excerpt}”</p>
            <p className="meta mt-1 font-mono">
              {r.clause.ref} · {r.clause.source}
            </p>
          </blockquote>
        </div>
      )}
    </li>
  );
}
