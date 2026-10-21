import { useEffect, useState, type ReactNode } from "react";
import { useMutation } from "@tanstack/react-query";
import { api } from "../../api/client";
import { ErrorBox, Icon, Spinner, Title } from "../../components/ui";

// "Pair Revit": the add-in's pairing window sends people here for a 6-digit code (P4.4 / P5).
export default function PairPage() {
  const pair = useMutation({ mutationFn: api.pairStart });
  const [left, setLeft] = useState(0);
  const server = window.location.origin;

  useEffect(() => {
    if (!pair.data) return;
    const until = Date.now() + pair.data.expires_in_s * 1000;
    const tick = () => setLeft(Math.max(0, Math.round((until - Date.now()) / 1000)));
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
  }, [pair.data]);

  const live = pair.data && left > 0;
  return (
    <div className="mx-auto max-w-[600px]">
      <Title>check from inside revit.</Title>

      <ol className="mt-8 space-y-3">
        <Step n={1} title="install">
          <p title="Unzip, close Revit, right-click install.ps1 → Run with PowerShell, then start Revit and choose Always Load.">unzip · run install.ps1 · Always Load</p>
          <a className="btn-secondary mt-3" href="/downloads/ComplianceChecker-revit2026.zip" download>
            <Icon name="download" /> add-in for Revit 2026
          </a>
        </Step>

        <Step n={2} title="pair">
          <p>Revit → Compliance → 1 Pair</p>
          <div className="mt-3 divide-y divide-line-subtle rounded-sm border border-line-subtle">
            <div className="flex items-baseline gap-4 px-3 py-2.5">
              <span className="w-24 text-xs text-fg-2">server URL</span>
              <span className="break-all font-mono text-sm">{server}</span>
            </div>
            <div className="flex items-center gap-4 px-3 py-2.5">
              <span className="w-24 text-xs text-fg-2">pairing code</span>
              {live ? (
                <span className="flex items-baseline gap-3">
                  <span className="font-mono text-2xl font-medium tracking-[0.3em]">{pair.data!.code}</span>
                  <span className="num text-fg-3">
                    {Math.floor(left / 60)}:{String(left % 60).padStart(2, "0")}
                  </span>
                </span>
              ) : (
                <button className="btn-primary" onClick={() => pair.mutate()} disabled={pair.isPending}>
                  {pair.isPending ? <Spinner /> : <Icon name="plug" />} {pair.data ? "get a new code" : "get a code"}
                </button>
              )}
            </div>
          </div>
          {pair.error ? (
            <div className="mt-3">
              <ErrorBox error={pair.error} title="couldn't create a code" onRetry={() => pair.mutate()} />
            </div>
          ) : null}

        </Step>

        <Step n={3} title="check">
          <p>2 Site Setup → 3 Run Check</p>
        </Step>
      </ol>
    </div>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: ReactNode }) {
  return (
    <li className="panel flex gap-4 p-5 text-sm text-fg-2">
      <span className="grid h-6 w-6 shrink-0 place-items-center rounded-sm border border-line font-mono text-xs text-fg">
        0{n}
      </span>
      <div className="min-w-0 flex-1">
        <h2 className="h2 mb-1 text-fg">{title}</h2>
        {children}
      </div>
    </li>
  );
}
