"""Where uploaded files live, next to the database (on the volume in the container).

    ifc/<model version>/   model.ifc.gz, mesh.json.gz, thumb.png, meta.json   (see ingest)
    drawings/<project>/    drawing.dxf and what is read from it
    live/<project>.json    the live pack for the plug-ins

Uploads from before the per-version folders were stored as ifc/<version>.ifc (+ .mesh.json,
.thumb.png); they are still found, and removed by the same calls.
"""

from __future__ import annotations

import shutil
from pathlib import Path

from compliance.ingest import IFC_GZ, MESH_GZ, META, THUMB
from compliance.store.repo import Store


def root(st: Store) -> Path:
    return Path(st.db.path).parent


def model_dir(st: Store, version_id: str) -> Path:
    return root(st) / "ifc" / version_id


def legacy_ifc(st: Store, version_id: str) -> Path:
    return root(st) / "ifc" / f"{version_id}.ifc"


def has_ifc(st: Store, version_id: str) -> bool:
    return (model_dir(st, version_id) / IFC_GZ).exists() or legacy_ifc(st, version_id).exists()


def thumbnail(st: Store, version_id: str) -> Path | None:
    legacy = legacy_ifc(st, version_id).with_suffix(".thumb.png")
    for p in (model_dir(st, version_id) / THUMB, legacy):
        if p.exists():
            return p
    return None


def meta(st: Store, version_id: str) -> Path:
    return model_dir(st, version_id) / META


def drawing_dir(st: Store, project_id: str) -> Path:
    return root(st) / "drawings" / project_id


def remove_model_files(st: Store, version_id: str, *, keep_preview: bool = False) -> None:
    """The uploaded IFC and its 3D view; with keep_preview the small thumbnail and meta stay."""
    folder = model_dir(st, version_id)
    if folder.exists():
        if keep_preview:
            for name in (IFC_GZ, MESH_GZ):
                (folder / name).unlink(missing_ok=True)
        else:
            shutil.rmtree(folder, ignore_errors=True)
    legacy = legacy_ifc(st, version_id)
    for p in (legacy, legacy.with_suffix(".mesh.json")):
        p.unlink(missing_ok=True)
    if not keep_preview:
        legacy.with_suffix(".thumb.png").unlink(missing_ok=True)


def remove_drawing(st: Store, project_id: str) -> None:
    shutil.rmtree(drawing_dir(st, project_id), ignore_errors=True)


def remove_live_pack(st: Store, project_id: str) -> None:
    (root(st) / "live" / f"{project_id}.json").unlink(missing_ok=True)
