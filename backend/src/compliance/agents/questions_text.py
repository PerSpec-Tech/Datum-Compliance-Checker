"""Question wording: Nemotron Nano rephrases the planner's template questions.

It never changes which questions are asked, their order or what they unlock (the planner,
decides that). If the answer doesn't line up one-to-one, the templates are kept.
"""

from __future__ import annotations

import json
import re
from typing import Any

from compliance.llm.client import LLMClient
from compliance.llm.prompts import render

SCHEMA = {
    "name": "questions",
    "schema": {
        "type": "object",
        "properties": {
            "questions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}, "prompt": {"type": "string"}},
                    "required": ["path", "prompt"],
                    "additionalProperties": False,
                },
            }
        },
        "required": ["questions"],
        "additionalProperties": False,
    },
}
MAX_LEN = 300
_TAIL = re.compile(r"[\s\"'{}\[\],]+$")


def reword(questions: list[dict[str, Any]], llm: LLMClient, *, job_id: str | None = None) -> int:
    """Rewrites prompts in place. Returns how many were changed."""
    if not questions:
        return 0
    payload = [
        {"path": q["path"], "prompt": q["prompt"], "unlocks": q["unlocks"]} for q in questions
    ]
    _, prompt = render("questions", questions_json=json.dumps(payload, ensure_ascii=False))
    out = llm.chat(
        "fast",
        [{"role": "user", "content": prompt}],
        schema=SCHEMA,
        reasoning=False,
        purpose="questions_text",
        job_id=job_id,
    ).data["questions"]
    if [o["path"] for o in out] != [q["path"] for q in questions]:
        return 0  # model reordered, merged or dropped questions: keep the templates
    changed = 0
    for q, o in zip(questions, out, strict=True):
        # JSON scraps the model sometimes leaves at the end ('…compliance.},{'), then whitespace.
        text = _TAIL.sub("", o["prompt"]).strip()
        # Keep the template if the rewrite is clipped or telegraphic (much shorter), or has
        # brackets left inside it.
        clean = not any(c in text for c in "{}[]")
        if clean and max(40, len(q["prompt"]) // 2) <= len(text) <= MAX_LEN and text != q["prompt"]:
            q["prompt"] = text
            changed += 1
    return changed
