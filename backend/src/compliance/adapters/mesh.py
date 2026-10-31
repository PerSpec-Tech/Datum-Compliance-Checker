"""IFC → lightweight triangle meshes for the web viewer.

One entry per element with geometry: {guid, parent, type, name, v: [x,y,z,…] metres, f: [i,j,k,…]}.
`parent` is the aggregating element's GlobalId (IfcStair for an IfcStairFlight), because results
refer to the element the adapter read, which may be the aggregate.
Doing this server-side keeps the browser free of a WebAssembly IFC parser; the viewer only needs
three.js. Coordinates are rounded to millimetres to keep the payload small.

The geometry pass (tessellate) is the slow part of reading a model, so it runs once per upload and
both the model reader (adapters.ifc) and the viewer mesh use its result.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as uel

from compliance.config import get_settings

SKIP = ("IfcOpeningElement", "IfcAnnotation", "IfcGrid")

# GlobalId → (vertices, faces) in world coordinates, metres of the file's unit.
Shapes = dict[str, tuple[tuple[float, ...], tuple[int, ...]]]


def settings() -> Any:
    s = ifcopenshell.geom.settings()
    s.set("use-world-coords", True)
    return s


def tessellate(ifc: ifcopenshell.file, progress: Callable[[float], None] | None = None) -> Shapes:
    """One multi-threaded geometry pass over the whole file. progress gets 0–100 now and then."""
    shapes: Shapes = {}
    it = ifcopenshell.geom.iterator(settings(), ifc, max(1, get_settings().geom_threads))
    if it.initialize():
        last = -1
        while True:
            sh = it.get()
            shapes[sh.guid] = (tuple(sh.geometry.verts), tuple(sh.geometry.faces))
            if progress is not None and (pct := int(it.progress())) != last:
                last = pct
                progress(pct)
            if not it.next():
                break
    return shapes


def mesh_from(ifc: ifcopenshell.file, shapes: Shapes) -> dict[str, Any]:
    """The viewer mesh from a geometry pass."""
    elements: list[dict[str, Any]] = []
    spaces: list[dict[str, Any]] = []
    context: list[dict[str, Any]] = []  # plot ground, roads, neighbouring buildings
    for guid, (verts, faces) in shapes.items():
        el = ifc.by_guid(guid)
        if el.is_a() in SKIP:
            continue
        agg = uel.get_aggregate(el)
        entry = {
            "guid": guid,
            "parent": agg.GlobalId if agg is not None and agg.is_a("IfcElement") else None,
            "type": el.is_a(),
            "name": getattr(el, "LongName", None) or el.Name or el.is_a(),
            "v": [round(v, 3) for v in verts],
            "f": list(faces),
        }
        container = uel.get_container(el)
        if el.is_a("IfcSpace"):
            spaces.append(entry)  # drawn as translucent volumes
        elif el.is_a("IfcSite") or (container is not None and container.is_a("IfcSite")):
            context.append(entry)
        else:
            elements.append(entry)
    return {"elements": elements, "spaces": spaces, "context": context}


def ifc_to_mesh(path: str | Path) -> dict[str, Any]:
    ifc = ifcopenshell.open(str(path))
    return mesh_from(ifc, tessellate(ifc))
