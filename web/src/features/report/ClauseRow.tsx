import { useState } from "react";
import { Link } from "react-router-dom";
import type { Result } from "../../api/types";
import { Chip, Icon, SourceBadge, StatusMark, fmt, humanPath } from "../../components/ui";

// One clause checked against one element: status, clause, measured / limit, fix-by. Click for detail.
export default function ClauseRow({ r }: { r: Result }) {
  const [open, setOpen] = useState(false);

  return (
    <li>
      <button
        className="grid w-full grid-cols-[104px_minmax(0,1fr)_auto] items-start gap-3 px-4 py-2.5 text-left transition-colors hover:bg-surface-raised"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="pt-0.5">
          <StatusMark status={r.status} />
        </span>
        <span className="min-w-0">
          <span className="block text-sm leading-5">{r.title}</span>
          <span className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-fg-3">
            <span className="font-mono" title={r.clause.source}>{r.clause.ref}</span>
            {r.rule_status === "draft" && (
              <Chip predicted title="Compiled from the clause text; not yet verified by a person">
                draft
              </Chip>
            )}
            {r.freshness.status === "possibly_superseded" && (
              <Chip title="Tavily found a notification that may change this clause">superseded?</Chip>
            )}

          </span>
        </span>
        <span className="text-right">
          {(r.measured !== null || r.limit !== null) && r.status !== "not_applicable" && (
            <span className="num block">
              {fmt(r.measured)}
              <span className="text-fg-3"> / {fmt(r.limit)}</span>
            </span>
          )}
          {r.fix_by && (
            <span className={`mt-0.5 block font-mono text-2xs ${r.status === "fail" ? "text-danger" : "text-fg-2"}`}>
              {r.fix_by.direction === "increase" ? "+" : "−"}
              {fmt(r.fix_by.amount)}
              {r.fix_by.unit ? ` ${r.fix_by.unit}` : ""}
            </span>
          )}
        </span>
      </button>

      {open && (
        <div className="space-y-3 border-t border-line-subtle bg-surface-low py-3 pl-[132px] pr-4 text-sm">
          <p className="text-fg-2">{r.message}</p>
          <blockquote className="border-l border-fg-2 pl-3 text-fg">
            <p className="whitespace-pre-line">“{r.clause.excerpt}”</p>
            <p className="meta mt-1 font-mono">
              {r.clause.ref} · {r.clause.source}
            </p>
          </blockquote>
          {r.facts_used.length > 0 && (
            <table className="w-full max-w-xl text-xs">
              <tbody>
                {r.facts_used.map((f) => (
                  <tr key={f.path} className="border-t border-line-subtle first:border-t-0">
                    <td className="py-1 pr-3 text-fg-2">{humanPath(f.path)}</td>
                    <td className="py-1 pr-3 text-right font-mono tabular-nums">{fmt(f.value)}</td>
                    <td className="py-1 text-right">
                      <SourceBadge source={f.source} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {r.guidance_note && (
            <p className="text-xs text-fg-2">
              <Icon name="info" size={14} className="mr-1.5 inline align-[-3px]" />
              {r.guidance_note.text} <span className="text-fg-3">({r.guidance_note.source})</span>
            </p>
          )}
          <div className="flex flex-wrap gap-4 text-xs">
            <Link
              to={`/rules/${encodeURIComponent(r.rule_id)}`}
              className="text-fg-2 underline decoration-line-strong underline-offset-4 hover:text-fg"
            >
              compiled rule <span className="font-mono">{r.rule_id}</span>
            </Link>
            {r.freshness.url && (
              <a
                href={r.freshness.url}
                target="_blank"
                rel="noreferrer"
                className="text-fg-2 underline decoration-line-strong underline-offset-4 hover:text-fg"
              >
                possible newer notification ↗
              </a>
            )}
          </div>
        </div>
      )}
    </li>
  );
}
