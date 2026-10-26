import { useMemo, useState, type FormEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { api, type ProjectSummary } from "../../api/client";
import { ErrorBox, Icon, Skeleton, Spinner, Title } from "../../components/ui";
import Sketch from "../../components/Sketch";
import { forgetProject, recentProjects, rememberProject } from "../../lib/recent";

// Saved projects: everything typed in the site setup is kept on the server with the model and its
// checks, so a project can be closed and opened again. There is no login, so the list is the
// projects this browser has opened; a project's link opens (and adds) it on any other device.

export default function ProjectsPage() {
  const qc = useQueryClient();
  const [ids, setIds] = useState(() => recentProjects().map((r) => r.id));
  const list = useQuery({
    queryKey: ["project-summaries", ids.join(",")],
    queryFn: () => (ids.length ? api.projectSummaries(ids) : Promise.resolve([])),
  });
  const sorted = useMemo(() => [...(list.data ?? [])].sort((a, b) => b.updated_at.localeCompare(a.updated_at)), [list.data]);

  const refresh = () => {
    setIds(recentProjects().map((r) => r.id));
    void qc.invalidateQueries({ queryKey: ["project-summaries"] });
  };

  return (
    <div className="mx-auto max-w-[1100px]">
      <div className="flex flex-wrap items-end gap-4">
        <div className="flex-1">
          <Title>projects.</Title>
          <p className="mt-2 max-w-[60ch] text-sm text-fg-2">
            Everything you set (the site, the plot, its roads, the planning facts) is saved with the model and its checks. Open a project's link on
            another device to see it there too.
          </p>
        </div>
        <Link to="/" className="btn-primary">
          <Icon name="upload" /> new check
        </Link>
      </div>

      <AddByLink onAdded={refresh} />

      {list.isLoading && (
        <div className="mt-6">
          <Skeleton rows={3} />
        </div>
      )}
      {list.error ? <ErrorBox error={list.error} title="couldn't load your projects" onRetry={() => void list.refetch()} /> : null}
      {list.data && sorted.length === 0 && (
        <div className="mt-8 rounded-md border border-dashed border-line px-6 py-10 text-center text-sm text-fg-2">
          No projects in this browser yet. <Link to="/" className="underline">Add a model</Link> or try a sample; it is saved as you go.
        </div>
      )}
      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {sorted.map((p) => (
          <ProjectCard key={p.id} p={p} onChanged={refresh} />
        ))}
      </div>
    </div>
  );
}

function ProjectCard({ p, onChanged }: { p: ProjectSummary; onChanged: () => void }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(p.name);
  const [busy, setBusy] = useState(false);
  const [copied, setCopied] = useState(false);
  const site = p.site.location && p.site.plot && p.site.sides;
  const c = p.last_check;
  const kind = p.source_kind === "dxf" ? "DXF · 2D" : p.source_kind === "revit" ? "Revit" : p.source_kind === "ifc" ? "IFC · 3D" : "no model";

  async function save(e: FormEvent) {
    e.preventDefault();
    if (!name.trim() || name.trim() === p.name) return setEditing(false);
    setBusy(true);
    try {
      const r = await api.renameProject(p.id, name);
      rememberProject({ id: p.id, name: r.name });
      setEditing(false);
      onChanged();
    } finally {
      setBusy(false);
    }
  }

  return (
    <article className="flex flex-col overflow-hidden rounded-md border border-line-subtle bg-surface">
      <Link to={`/w/${p.id}`} className="relative block bg-surface-low">
        <Sketch src={`/api/projects/${p.id}/thumbnail`} className="h-40 w-full p-3" />
        <span className="absolute left-3 top-3 rounded-sm border border-line-subtle bg-surface px-2 py-0.5 font-mono text-2xs text-fg-2">{kind}</span>
      </Link>
      <div className="flex flex-1 flex-col gap-2 border-t border-line-subtle px-3 py-3">
        {editing ? (
          <form onSubmit={save} className="flex gap-1">
            <input className="input h-8 py-0 text-sm" value={name} onChange={(e) => setName(e.target.value)} autoFocus aria-label="project name" />
            <button className="btn-primary h-8 px-2" disabled={busy} aria-label="save name">
              {busy ? <Spinner /> : <Icon name="check" size={14} />}
            </button>
          </form>
        ) : (
          <div className="flex items-center gap-2">
            <Link to={`/w/${p.id}`} className="min-w-0 flex-1 truncate text-sm font-medium hover:underline" title={p.name}>
              {p.name}
            </Link>
            <button className="btn-ghost h-7 px-1.5" onClick={() => setEditing(true)} title="Rename" aria-label="rename">
              <Icon name="edit" size={13} />
            </button>
          </div>
        )}
        <div className="flex flex-wrap gap-1.5 text-2xs">
          <Flag ok={p.site.location} label="location" />
          <Flag ok={p.site.plot} label="plot" />
          <Flag ok={p.site.sides} label="roads & sides" />
        </div>
        <p className="font-mono text-2xs text-fg-3">
          {c ? (
            <>
              <span className={c.fail ? "text-danger" : ""}>✕ {c.fail ?? 0}</span> · ? {c.unverifiable ?? 0} · ✓ {c.pass ?? 0} · checked {new Date(c.at).toLocaleDateString()}
            </>
          ) : site ? (
            "site saved · not checked yet"
          ) : (
            "saved · site to finish"
          )}
        </p>
        <div className="mt-auto flex items-center gap-1 pt-1">
          <Link to={`/w/${p.id}`} className="btn-secondary h-8 flex-1 justify-center text-xs">
            <Icon name="arrow" size={13} /> open
          </Link>
          {!site && (
            <Link to={`/w/${p.id}?site=1`} className="btn-ghost h-8 text-xs" title="Finish the site setup">
              <Icon name="pin" size={13} /> site
            </Link>
          )}
          <button
            className="btn-ghost h-8 px-2 text-xs"
            title="Copy the project's link"
            onClick={() => {
              void navigator.clipboard?.writeText(`${window.location.origin}/w/${p.id}`);
              setCopied(true);
              setTimeout(() => setCopied(false), 1500);
            }}
          >
            <Icon name={copied ? "check" : "link"} size={13} />
          </button>
          <button
            className="btn-ghost h-8 px-2 text-xs"
            title="Remove from this list (the project stays on the server; its link still opens it)"
            onClick={() => {
              forgetProject(p.id);
              onChanged();
            }}
          >
            <Icon name="x" size={13} />
          </button>
        </div>
      </div>
    </article>
  );
}

function Flag({ ok, label }: { ok: boolean; label: string }) {
  return (
    <span className={`flex items-center gap-1 rounded-sm border px-1.5 py-0.5 ${ok ? "border-line-subtle text-fg-2" : "border-dashed border-accent text-accent"}`}>
      <Icon name={ok ? "check" : "dash"} size={11} /> {label}
    </span>
  );
}

/** Open a project saved on another device: paste its link (or id). */
function AddByLink({ onAdded }: { onAdded: () => void }) {
  const [text, setText] = useState("");
  const [note, setNote] = useState<string | null>(null);
  async function add(e: FormEvent) {
    e.preventDefault();
    const id = /([0-9a-f]{32})/i.exec(text)?.[1];
    if (!id) return setNote("That isn't a project link.");
    const [found] = await api.projectSummaries([id]);
    if (!found) return setNote("No project with that link on this server.");
    rememberProject({ id, name: found.name });
    setText("");
    setNote(null);
    onAdded();
  }
  return (
    <form onSubmit={add} className="mt-6 flex max-w-[560px] gap-2">
      <div className="relative flex-1">
        <span className="pointer-events-none absolute left-2.5 top-1/2 -translate-y-1/2 text-fg-3">
          <Icon name="link" size={14} />
        </span>
        <input className="input h-9 pl-8" placeholder="paste a project link to open it here" value={text} onChange={(e) => setText(e.target.value)} />
      </div>
      <button className="btn-secondary h-9" disabled={!text.trim()}>
        <Icon name="check" size={14} /> add
      </button>
      {note && <p className="self-center text-xs text-danger">{note}</p>}
    </form>
  );
}
