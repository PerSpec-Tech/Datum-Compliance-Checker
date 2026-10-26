import { lazy, Suspense } from "react";
import { Navigate, NavLink, Route, Routes, useLocation, useParams } from "react-router-dom";
import { Icon, Skeleton, type IconName } from "./components/ui";
import ThemeToggle from "./components/ThemeToggle";
import NewCheckPage from "./features/upload/NewCheckPage";

const BriefPage = lazy(() => import("./features/brief/BriefPage"));
const ReportPage = lazy(() => import("./features/report/ReportPage"));
const RulesPage = lazy(() => import("./features/rules/RulesPage"));
const PairPage = lazy(() => import("./features/about/PairPage"));
const ProjectsPage = lazy(() => import("./features/projects/ProjectsPage"));
const WorkspacePage = lazy(() => import("./features/workspace/WorkspacePage"));

const NAV: { to: string; label: string; icon: IconName; end?: boolean }[] = [
  { to: "/", label: "new check", icon: "upload", end: true },
  { to: "/projects", label: "projects", icon: "list" },
  { to: "/revit", label: "pair Revit · AutoCAD", icon: "plug" },
  { to: "/rules", label: "rules", icon: "book" },
];

// The tool's glyph: a checklist with a tick (§16). Monochrome; used for the favicon too.
function Glyph() {
  return (
    <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden>
      <path d="M3 4h9M3 8h6M3 12h4" />
      <path d="M10 13l2.5 2.5L17 10" />
    </svg>
  );
}

// Old progress links (P4): the check now runs inside the workspace.
function ToWorkspace() {
  const { projectId, jobId } = useParams();
  return <Navigate to={`/w/${projectId}?job=${jobId}`} replace />;
}

export default function App() {
  const path = useLocation().pathname;
  // The report is a document: no sidebar, prints on its own.
  if (path.startsWith("/reports/"))
    return (
      <main className="min-h-screen bg-canvas px-5 py-8 print:p-0">
        <Suspense fallback={<Skeleton />}>
          <Routes>
            <Route path="/reports/:reportId" element={<ReportPage />} />
          </Routes>
        </Suspense>
      </main>
    );
  // The workspace is full screen, like a CAD program: no sidebar.
  if (path.startsWith("/w/"))
    return (
      <Suspense fallback={<Skeleton />}>
        <Routes>
          <Route path="/w/:projectId" element={<WorkspacePage />} />
        </Routes>
      </Suspense>
    );
  return (
    <div className="min-h-screen lg:pl-[var(--sidebar)]">
      <aside className="z-[1000] flex flex-col border-b border-line-subtle bg-canvas lg:fixed lg:inset-y-0 lg:left-0 lg:w-[var(--sidebar)] lg:border-b-0 lg:border-r">
        <NavLink to="/" className="flex h-14 items-center gap-2.5 px-5 text-fg">
          <Glyph />
          <span className="text-[15px] font-semibold tracking-[-0.02em]">
            compliance check<span className="stop">.</span>
          </span>
        </NavLink>
        <nav className="flex gap-1 overflow-x-auto px-3 pb-3 lg:flex-col lg:gap-0.5 lg:pb-0 lg:pt-2" aria-label="Primary">
          {NAV.map((n) => (
            <NavLink
              key={n.to}
              to={n.to}
              end={n.end}
              className={({ isActive }) =>
                `relative flex h-8 shrink-0 items-center gap-2.5 rounded-sm px-2.5 text-sm transition-colors ${
                  isActive ? "bg-surface text-fg" : "text-fg-2 hover:bg-surface hover:text-fg"
                }`
              }
            >
              {({ isActive }) => (
                <>
                  {isActive && <span className="absolute inset-y-1.5 left-0 w-[2px] bg-accent" aria-hidden />}
                  <Icon name={n.icon} />
                  {n.label}
                </>
              )}
            </NavLink>
          ))}
        </nav>
        <div className="mt-auto hidden border-t border-line-subtle px-5 py-4 lg:block">
          <p className="font-mono text-2xs leading-5 text-fg-3" title="A design aid, not a permit. Every result cites its clause.">
            PMC · UDCPR 2020
          </p>
          <p className="mt-1 text-2xs leading-4 text-fg-3">A design aid, not a permit. Maps © OpenStreetMap contributors.</p>
          <div className="mt-2 flex items-center justify-between">
            <p className="text-xs font-semibold tracking-[-0.02em] text-fg-2">
              perspec<span className="stop">.</span>
            </p>
            <ThemeToggle />
          </div>
        </div>
      </aside>
      <main className="mx-auto w-full max-w-[1440px] px-5 py-8 lg:px-10">
        <Suspense fallback={<Skeleton />}>
          <Routes>
            <Route path="/" element={<NewCheckPage />} />
            <Route path="/p/:projectId/brief" element={<BriefPage />} />
            <Route path="/p/:projectId/jobs/:jobId" element={<ToWorkspace />} />
            <Route path="/reports/:reportId" element={<ReportPage />} />
            <Route path="/projects" element={<ProjectsPage />} />
            <Route path="/rules" element={<RulesPage />} />
            <Route path="/rules/:ruleId" element={<RulesPage />} />
            <Route path="/about" element={<Navigate to="/" replace />} />
            <Route path="/revit" element={<PairPage />} />
            <Route path="*" element={<p className="text-fg-2">page not found.</p>} />
          </Routes>
        </Suspense>
      </main>
    </div>
  );
}
