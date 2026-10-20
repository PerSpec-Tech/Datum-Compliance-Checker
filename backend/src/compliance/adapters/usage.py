"""First-pass room use from the room name (same keywords as the Revit add-in's UsageGuess).
Unrecognised names stay unknown; the Nemotron classifier (P3.7) or the architect fills them."""

from __future__ import annotations

import re
from typing import Any

_RULES = [
    ("bed|bedroom|br|master", "bedroom"),
    ("living|hall|drawing|family|lounge", "living"),
    ("kitchen|kit|pantry", "kitchen"),
    (r"wc|w\.c\.|water closet|powder", "wc"),
    ("toilet|bath|bathroom|washroom|wash", "bathroom"),
    ("corridor|passage", "corridor"),
    ("stair|staircase|stairwell", "stair"),
    ("lobby|foyer|entrance", "lobby"),
    ("lift|elevator", "utility"),  # after lobby: "Lift Lobby" is a lobby
    ("balcony|terrace|verandah|sit-out|deck", "other"),
    ("parking|garage|stilt", "parking"),
    ("office|cabin|workstation", "office"),
    ("shop|retail|showroom", "retail"),
    ("store|storage|utility|services|electrical|shaft", "storage"),
    ("dining|study|room", "habitable"),
]
_COMPILED = [(re.compile(rf"(^|[^a-z])({p})([^a-z]|$)", re.I), u) for p, u in _RULES]


def guess(name: str) -> dict[str, Any]:
    for pattern, usage in _COMPILED:
        if pattern.search(name or ""):
            return {
                "value": usage,
                "source": "inferred",
                "confidence": 0.7,
                "note": "from room name",
            }
    return {"value": None, "source": "default", "note": f"use of '{name}' not recognised"}
