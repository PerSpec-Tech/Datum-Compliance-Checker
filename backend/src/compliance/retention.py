"""What is kept, and for how long. Runs on start and then every few hours (see main).

- Only a project's latest model version is kept; older ones go as soon as a new one arrives.
- A project not used for Settings.retention_files_days loses its uploaded files (IFC, DXF and
  the 3D view); its reports stay, and the model can be uploaded again to see it in 3D.
- A project not used for Settings.retention_project_days is deleted completely.
"""

from __future__ import annotations

import logging
from typing import Any

from compliance import files
from compliance.config import get_settings
from compliance.store.repo import Store

log = logging.getLogger(__name__)


def prune_versions(st: Store, project_id: str) -> int:
    """Remove every model version but the latest, with its files."""
    old = st.model_versions(project_id)[1:]
    for vid in old:
        files.remove_model_files(st, vid)
    st.delete_model_versions(old)
    return len(old)


def sweep(st: Store) -> dict[str, Any]:
    s = get_settings()
    deleted = st.idle_projects(s.retention_project_days)
    for pid in deleted:
        for vid in st.model_versions(pid):
            files.remove_model_files(st, vid)
        files.remove_drawing(st, pid)
        files.remove_live_pack(st, pid)
        st.delete_project(pid)

    expired = 0
    for pid in st.idle_projects(s.retention_files_days):
        for vid in st.model_versions(pid):
            if files.has_ifc(st, vid):
                files.remove_model_files(st, vid, keep_preview=True)
                expired += 1
        if files.drawing_dir(st, pid).exists():
            files.remove_drawing(st, pid)
            expired += 1

    pruned = 0
    for row in st.db.query("SELECT id FROM projects"):
        pruned += prune_versions(st, row["id"])

    out = {"projects_deleted": len(deleted), "files_expired": expired, "versions_pruned": pruned}
    if any(out.values()):
        log.info("retention sweep: %s", out)
    return out
