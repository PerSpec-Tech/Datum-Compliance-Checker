"""Explainer: Nemotron Super turns a finished report into a short plain-language summary
with fix advice. It reads the report only and can't change any status. Any rule id it invents
is dropped; any regulation number it mentions that isn't in the report triggers one regeneration,
after which offending sentences are removed.
"""

from __future__ import annotations

import json
import re
from typing import Any

from compliance.llm.client import LLMClient
from compliance.llm.prompts import render

SCHEMA = {
    "name": "explanation",
    "schema": {
        "type": "object",
        "properties": {
            "summary": {"type": "string"},
            "failures": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "rule_id": {"type": "string"},
                        "element_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "explanation": {"type": "string"},
                    },
                    "required": ["rule_id", "element_id", "explanation"],
                    "additionalProperties": False,
                },
            },
        },
        "required": ["summary", "failures"],
        "additionalProperties": False,
    },
}
MAX_FAILS = 25
# Things that look like regulation references: "9.29.1", "14.2.1.2", "Table 9-G", "Regulation 6.3".
_REF = re.compile(r"\b(?:\d+\.\d+(?:\.\d+)*|Table\s*(?:No\.?\s*)?\d+-[A-Z])\b", re.IGNORECASE)


def compact(report: dict[str, Any]) -> dict[str, Any]:
    """The part of the report the model needs (keeps prompts small)."""

    def row(r: dict[str, Any]) -> dict[str, Any]:
        return {
            "rule_id": r["rule_id"],
            "element_id": (r["element"] or {}).get("id"),
            "title": r["title"],
            "severity": r["severity"],
            "message": r["message"],
            "fix_by": r["fix_by"],
            "clause": r["clause"]["ref"],
        }

    fails = [r for r in report["results"] if r["status"] == "fail"][:MAX_FAILS]
    unverifiable = [r for r in report["results"] if r["status"] == "unverifiable"][:10]
    advisories = [r for r in report["results"] if r["status"] == "advisory"][:5]
    return {
        "summary": report["summary"],
        "failures": [row(r) for r in fails],
        "cannot_verify": [
            {"title": r["title"], "needs": r["missing_inputs"][:3]} for r in unverifiable
        ],
        "advisories": [{"title": r["title"], "message": r["message"]} for r in advisories],
        "fsi": report.get("fsi"),
        "questions": [
            {"prompt": q["prompt"], "unlocks": q["unlocks"]} for q in report["questions"][:5]
        ],
    }


def explain(report: dict[str, Any], llm: LLMClient, *, job_id: str | None = None) -> str:
    data = compact(report)
    text = json.dumps(data, ensure_ascii=False)
    allowed_refs = {m.group(0).lower() for m in _REF.finditer(text)}
    _, prompt = render("explain", report_json=text)
    messages = [{"role": "user", "content": prompt}]

    out: dict[str, Any] = {}
    for attempt in range(2):
        out = llm.chat(
            "agent",
            messages,
            schema=SCHEMA,
            reasoning=False,
            max_tokens=2500,
            purpose="explain",
            job_id=job_id,
        ).data
        stray = _stray_refs(out, allowed_refs)
        if not stray:
            break
        if attempt == 0:
            messages = [
                *messages,
                {"role": "assistant", "content": json.dumps(out)},
                {
                    "role": "user",
                    "content": "Remove these references, they are not in the report: "
                    f"{sorted(stray)}.",
                },
            ]
        else:
            out = _strip_sentences(out, stray)

    known = {(f["rule_id"], f["element_id"]) for f in data["failures"]}
    lines = [out["summary"].strip()]
    titles = {(f["rule_id"], f["element_id"]): f["title"] for f in data["failures"]}
    for f in out["failures"]:
        key = (f["rule_id"], f["element_id"])
        if key in known and f["explanation"].strip():
            where = f" ({f['element_id']})" if f["element_id"] else ""
            lines.append(f"• {titles[key]}{where}: {f['explanation'].strip()}")
    return "\n".join(lines)


def _stray_refs(out: dict[str, Any], allowed: set[str]) -> set[str]:
    texts = [out["summary"], *(f["explanation"] for f in out["failures"])]
    return {
        m.group(0) for t in texts for m in _REF.finditer(t) if m.group(0).lower() not in allowed
    }


def _strip_sentences(out: dict[str, Any], stray: set[str]) -> dict[str, Any]:
    def clean(t: str) -> str:
        sentences = re.split(r"(?<=[.!?])\s+", t)
        return " ".join(s for s in sentences if not any(ref in s for ref in stray))

    return {
        "summary": clean(out["summary"]),
        "failures": [{**f, "explanation": clean(f["explanation"])} for f in out["failures"]],
    }
