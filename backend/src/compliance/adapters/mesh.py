"""IFC → lightweight triangle meshes for the web viewer (P6.8).

One entry per element with geometry: {guid, parent, type, name, v: [x,y,z,…] metres, f: [i,j,k,…]}.
`parent` is the aggregating element's GlobalId (IfcStair for an IfcStairFlight), because results
refer to the element the adapter read, which may be the aggregate.
Doing this server-side keeps the browser free of a WebAssembly IFC parser; the viewer only needs
three.js. Coordinates are rounded to millimetres to keep the payload small.
"""

from __future__ import annotations

import multiprocessing
from pathlib import Path
from typing import Any

import ifcopenshell
import ifcopenshell.geom
import ifcopenshell.util.element as uel

SKIP = ("IfcOpeningElement", "IfcAnnotation", "IfcGrid")


def ifc_to_mesh(path: str | Path) -> dict[str, Any]:
    ifc = ifcopenshell.open(str(path))
    settings = ifcopenshell.geom.settings()
    settings.set("use-world-coords", True)
    elements: list[dict[str, Any]] = []
    spaces: list[dict[str, Any]] = []
    context: list[dict[str, Any]] = []  # plot ground, roads, neighbouring buildings
    it = ifcopenshell.geom.iterator(settings, ifc, max(1, multiprocessing.cpu_count() - 1))
    if it.initialize():
        while True:
            shape = it.get()
            el = ifc.by_guid(shape.guid)
            verts = [round(v, 3) for v in shape.geometry.verts]
            agg = uel.get_aggregate(el)
            entry = {
                "guid": shape.guid,
                "parent": agg.GlobalId if agg is not None and agg.is_a("IfcElement") else None,
                "type": el.is_a(),
                "name": getattr(el, "LongName", None) or el.Name or el.is_a(),
                "v": verts,
                "f": list(shape.geometry.faces),
            }
            container = uel.get_container(el)
            if el.is_a() in SKIP:
                pass
            elif el.is_a("IfcSpace"):
                spaces.append(entry)  # drawn as translucent volumes
            elif el.is_a("IfcSite") or (container is not None and container.is_a("IfcSite")):
                context.append(entry)
            else:
                elements.append(entry)
            if not it.next():
                break
    return {"elements": elements, "spaces": spaces, "context": context}
