// Per-browser list of the projects opened here (the projects page and "recent"). The server is
// the record; there is no login, so this list is what makes a project "mine".
export interface RecentProject {
  id: string;
  name: string;
  at: string;
  reportId?: string;
}

const KEY = "cc.recent";

export function recentProjects(): RecentProject[] {
  try {
    return JSON.parse(localStorage.getItem(KEY) ?? "[]") as RecentProject[];
  } catch {
    return [];
  }
}

export function rememberProject(p: Omit<RecentProject, "at">) {
  try {
    const rest = recentProjects().filter((r) => r.id !== p.id);
    const prev = recentProjects().find((r) => r.id === p.id);
    const next = [{ ...prev, ...p, name: p.name || prev?.name || "Project", at: new Date().toISOString() }, ...rest].slice(0, 50);
    localStorage.setItem(KEY, JSON.stringify(next));
  } catch {
    /* storage unavailable */
  }
}

export function forgetProject(id: string) {
  try {
    localStorage.setItem(KEY, JSON.stringify(recentProjects().filter((r) => r.id !== id)));
  } catch {
    /* storage unavailable */
  }
}
