"""Room-use classifier (P3.7): Nemotron Nano names the use of rooms the keyword guess couldn't.

Only fills spaces whose usage is unknown (source "default") or a weak inference; never touches a
declared value. Low-confidence answers are left unknown so the planner asks instead (D4).
"""

from __future__ import annotations

from typing import Any

from compliance.llm.client import LLMClient
from compliance.llm.prompts import render

USAGES = [
    "habitable", "bedroom", "living", "kitchen", "bathroom", "wc", "corridor", "stair", "lobby",
    "parking", "office", "retail", "assembly", "storage", "utility", "other",
]  # fmt: skip
MIN_CONFIDENCE = 0.6
BATCH = 60

SCHEMA = {
    "name": "room_uses",
    "schema": {
        "type": "object",
        "properties": {
            "rooms": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string"},
                        "usage": {"anyOf": [{"type": "string", "enum": USAGES}, {"type": "null"}]},
                        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    },
                    "required": ["id", "usage", "confidence"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["rooms"],
        "additionalProperties": False,
    },
}


def needs_classification(space: dict[str, Any]) -> bool:
    u = space["usage"]
    if u["source"] == "declared":
        return False
    return u["value"] is None or (
        u["source"] == "inferred" and (u.get("confidence") or 0) < MIN_CONFIDENCE
    )


def classify_spaces(
    model: dict[str, Any], llm: LLMClient, *, job_id: str | None = None
) -> str | None:
    todo = [s for s in model["spaces"] if needs_classification(s)]
    if not todo:
        return None
    _, system = render("classify")
    by_id = {s["id"]: s for s in todo}
    filled = unsure = 0
    for start in range(0, len(todo), BATCH):
        batch = todo[start : start + BATCH]
        listing = "\n".join(f'{s["id"]}: "{s["name"]}"' for s in batch)
        result = llm.chat(
            "fast",
            [{"role": "system", "content": system}, {"role": "user", "content": listing}],
            schema=SCHEMA,
            reasoning=False,
            purpose="classify_usage",
            job_id=job_id,
        )
        for row in result.data["rooms"]:
            space = by_id.get(row["id"])
            if space is None:
                continue  # an id we didn't send: ignore
            if row["usage"] is None or row["confidence"] < MIN_CONFIDENCE:
                unsure += 1
                continue
            space["usage"] = {
                "value": row["usage"],
                "source": "inferred",
                "confidence": round(row["confidence"], 2),
                "note": f"classified from the room name '{space['name']}' by Nemotron",
            }
            filled += 1
    msg = f"Nemotron classified {filled} room{'s' if filled != 1 else ''}"
    return msg + (f"; {unsure} left for you to confirm" if unsure else "")
