"""Layer-role agent: Nemotron Nano suggests what each unknown DXF layer is.

Only layers the PreDCR table and the user haven't mapped are sent. Suggestions below
MIN_CONFIDENCE are dropped (the layer stays "not understood" and the web table asks). Suggestions
are stored apart from the user's choices and shown dashed until confirmed (guidelines §10).
"""

from __future__ import annotations

import json
from typing import Any

from compliance.llm.client import LLMClient
from compliance.llm.prompts import render

ROLES = [
    "plot", "road", "footprint", "floor", "floor_height", "ground", "fsi_resi", "fsi_comm",
    "fsi_other", "carpet", "room", "door", "window", "stair", "balcony", "parking", "ignore",
]  # fmt: skip
MIN_CONFIDENCE = 0.6
BATCH = 60

SCHEMA = {
    "name": "layer_roles",
    "schema": {
        "type": "object",
        "properties": {
            "layers": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "layer": {"type": "string"},
                        "role": {"anyOf": [{"type": "string", "enum": ROLES}, {"type": "null"}]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["layer", "role", "confidence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["layers"],
        "additionalProperties": False,
    },
}


def suggest_roles(
    profiles: list[dict[str, Any]], llm: LLMClient, *, job_id: str | None = None
) -> dict[str, dict[str, Any]]:
    """{layer: {"role", "confidence"}} for unknown layers the model is reasonably sure about."""
    todo = [p for p in profiles if p["role"] is None]
    if not todo:
        return {}
    _, system = render("layers")
    names = {p["layer"] for p in todo}
    out: dict[str, dict[str, Any]] = {}
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        listing = "\n".join(
            json.dumps({k: v for k, v in p.items() if k != "role"}, ensure_ascii=False)
            for p in batch
        )
        result = llm.chat(
            "fast",
            [{"role": "system", "content": system}, {"role": "user", "content": listing}],
            schema=SCHEMA,
            reasoning=False,
            temperature=0,
            purpose="layer_roles",
            job_id=job_id,
        )
        for row in result.data["layers"]:
            if row["layer"] not in names:
                continue  # a layer we didn't send: ignore
            if row["role"] is None or row["confidence"] < MIN_CONFIDENCE:
                continue
            out[row["layer"]] = {"role": row["role"], "confidence": round(row["confidence"], 2)}
    return _settle_floor_layers(out, {p["layer"]: p for p in todo})


def _settle_floor_layers(
    out: dict[str, dict[str, Any]], profiles: dict[str, dict[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Floor frames and section floor-heights both carry floor names; geometry tells them apart
    (a frame contains the plan's outlines, a section rectangle contains nothing), so that call is
    made here, not by the model."""
    for layer, s in out.items():
        p = profiles.get(layer, {})
        if s["role"] in ("floor", "floor_height") and p.get("holds_floor_names"):
            s["role"] = "floor" if p.get("contains_outlines_of") else "floor_height"
    return out
