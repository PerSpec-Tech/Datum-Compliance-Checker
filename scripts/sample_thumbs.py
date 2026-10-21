"""Thumbnails of the web samples for their cards, showing what is in each file: the DXF's
ground-floor plan (<file>.svg) and the IFC's building in 3D (<file>.png), in web/public/samples/.

Usage: just make-samples   (runs after the samples are written)
"""

from __future__ import annotations

import sys
from pathlib import Path

from compliance.adapters.dxf import drawing
from compliance.adapters.mesh import ifc_to_mesh
from compliance.thumbnail import floor_svg, mesh_png

WEB = Path(__file__).resolve().parents[1] / "web" / "public" / "samples"


def main() -> int:
    for old in [*WEB.glob("*.svg"), *WEB.glob("*.png")]:
        old.unlink()
    for path in sorted(WEB.glob("*.dxf")):
        out = path.with_name(path.name + ".svg")
        out.write_text(floor_svg(drawing(path)) or "", encoding="utf-8")
        print(f"wrote {out.name}")
    for path in sorted(WEB.glob("*.ifc")):
        out = path.with_name(path.name + ".png")
        out.write_bytes(mesh_png(ifc_to_mesh(path)))
        print(f"wrote {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
