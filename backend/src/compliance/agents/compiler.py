"""Rule compiler (P3.5): regulation text → draft rule, checked before anyone sees it.

Nemotron Super drafts the rule; then deterministic checks run, and any failure goes back to the
model (at most 2 retries):
  1. rule + table documents match the schemas
  2. every expression compiles in the safe evaluator (engine/expr.py)
  3. every path it reads exists in the BuildingModel (engine/catalog.py)
  4. every number it uses appears in the clause text (unit conversions allowed) — anti-hallucination
  5. it runs on all fixture buildings without an evaluation error (dry run)
Optionally Nemotron Ultra reviews the draft against the clause. Output is always status "draft";
only a person sets "verified" (D2, CLAUDE.md).
"""

from __future__ import annotations

import ast
import json
import re
import tempfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

from compliance.config import REPO_ROOT, get_settings
from compliance.engine.catalog import catalog
from compliance.engine.evaluate import evaluate
from compliance.engine.rules import EXPR_FIELDS, RuleBase, RuleError, _load_rule
from compliance.llm.client import LLMClient
from compliance.llm.models import role
from compliance.llm.prompts import render, version_tag
from compliance.schemas import errors as schema_errors

MAX_RETRIES = 2
FIXTURES = ("compliant_house", "violating_apartment", "missing_site")
EXAMPLE_RULES = ("udcpr2020.ch9.exit-door-width", "pmc.tod.max-fsi")
TRIVIAL_NUMBERS = {0.0, 1.0}
_NUMBER = re.compile(r"(?<![\w.])(\d+(?:\.\d+)?)")

_EXPR = {"anyOf": [{"type": "string"}, {"type": "null"}]}
LLM_SCHEMA = {
    "name": "draft_rule",
    "schema": {
        "type": "object",
        "properties": {
            "slug": {"type": "string", "pattern": "^[a-z0-9][a-z0-9-]{2,60}$"},
            "title": {"type": "string"},
            "severity": {"type": "string", "enum": ["critical", "major", "minor"]},
            "kind": {"type": "string", "enum": ["check", "advisory"]},
            "for_each": {
                "anyOf": [
                    {
                        "type": "string",
                        "enum": [
                            "spaces",
                            "areas",
                            "stairs",
                            "doors",
                            "levels",
                            "units",
                            "site.edges",
                        ],
                    },
                    {"type": "null"},
                ]
            },
            "applies_when": _EXPR,
            "limit": _EXPR,
            "measured": _EXPR,
            "check": {"type": "string"},
            "message": {"type": "string"},
            "fix_unit": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "new_tables": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "pattern": "^[a-z0-9_]+$"},
                        "description": {"type": "string"},
                        "unit": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                        "kind": {"type": "string", "enum": ["map", "bands"]},
                        "map": {
                            "anyOf": [
                                {
                                    "type": "object",
                                    "additionalProperties": {
                                        "type": ["number", "string", "boolean", "null"]
                                    },
                                },
                                {"type": "null"},
                            ]
                        },
                        "bands": {
                            "anyOf": [
                                {
                                    "type": "array",
                                    "items": {
                                        "type": "object",
                                        "properties": {
                                            "min": {"type": "number"},
                                            "max": {"type": ["number", "null"]},
                                            "value": {
                                                "type": ["number", "string", "boolean", "null"]
                                            },
                                        },
                                        "required": ["min", "max", "value"],
                                        "additionalProperties": False,
                                    },
                                },
                                {"type": "null"},
                            ]
                        },
                    },
                    "required": ["name", "description", "unit", "kind", "map", "bands"],
                    "additionalProperties": False,
                },
            },
            "notes": {"type": "string"},
        },
        "required": [
            "slug",
            "title",
            "severity",
            "kind",
            "for_each",
            "applies_when",
            "limit",
            "measured",
            "check",
            "message",
            "fix_unit",
            "new_tables",
            "notes",
        ],
        "additionalProperties": False,
    },
}
REVIEW_SCHEMA = {
    "name": "review",
    "schema": {
        "type": "object",
        "properties": {
            "verdict": {"type": "string", "enum": ["faithful", "issues"]},
            "notes": {"type": "array", "items": {"type": "string"}},
        },
        "required": ["verdict", "notes"],
        "additionalProperties": False,
    },
}


@dataclass
class Clause:
    text: str
    ref: str
    source: str
    authority: str


@dataclass
class CompileResult:
    ok: bool
    rule: dict[str, Any] | None
    tables: list[dict[str, Any]]
    errors: list[str]
    dry_run: dict[str, dict[str, int]]
    attempts: int
    notes: str = ""
    review: dict[str, Any] | None = None
    history: list[list[str]] = field(default_factory=list)  # errors per attempt
    review_history: list[dict[str, Any]] = field(default_factory=list)  # earlier reviews
    draft: dict[str, Any] = field(default_factory=dict, repr=False)  # raw model output

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "rule": self.rule,
            "tables": self.tables,
            "errors": self.errors,
            "dry_run": self.dry_run,
            "attempts": self.attempts,
            "notes": self.notes,
            "review": self.review,
            "review_history": self.review_history,
            "history": self.history,
        }


def compile_clause(
    clause: Clause,
    llm: LLMClient,
    rulebase: RuleBase,
    *,
    review: bool = False,
    job_id: str | None = None,
) -> CompileResult:
    """Super drafts → deterministic checks (≤ 2 retries) → optional Ultra review → if Ultra finds
    issues, one revision by Super with the review notes, re-checked and re-reviewed."""
    _, prompt = render(
        "compiler",
        catalog=catalog().describe(),
        tables=_describe_tables(rulebase),
        examples=_examples(rulebase),
        authority=clause.authority,
        clause_ref=clause.ref,
        clause_text=clause.text.strip(),
    )
    messages: list[dict[str, Any]] = [{"role": "user", "content": prompt}]
    result = _draft_until_valid(clause, llm, rulebase, messages, job_id)
    if not (result.ok and review):
        return result

    result.review = _review(result.rule, result.tables, clause, llm, job_id)
    if result.review["verdict"] == "faithful":
        return result

    first_review = result.review
    revise = [
        *messages,
        {"role": "assistant", "content": json.dumps(result.draft)},
        {
            "role": "user",
            "content": "A senior reviewer found these issues with your rule:\n- "
            + "\n- ".join(first_review["notes"])
            + "\nRevise the rule to fix them where the building model allows it (see the "
            "catalogue, e.g. derived.space_min_width_m[item.id] for room widths). If something "
            "can't be "
            "encoded, say so in notes. Return the full corrected rule.",
        },
    ]
    revised = _draft_until_valid(clause, llm, rulebase, revise, job_id)
    if not revised.ok:
        result.review_history = [first_review]
        return result  # keep the first valid draft; its review explains the remaining issues
    revised.review = _review(revised.rule, revised.tables, clause, llm, job_id)
    revised.review_history = [first_review]
    revised.attempts += result.attempts
    revised.history = result.history + revised.history
    return revised


def _draft_until_valid(
    clause: Clause, llm: LLMClient, rulebase: RuleBase, messages: list[dict[str, Any]], job_id
) -> CompileResult:
    history: list[list[str]] = []
    rule = tables = None
    dry: dict[str, dict[str, int]] = {}
    draft: dict[str, Any] = {}
    for attempt in range(1, MAX_RETRIES + 2):
        draft = llm.chat(
            "agent",
            messages,
            schema=LLM_SCHEMA,
            reasoning=True,
            max_tokens=6000,
            purpose="compile_rule",
            job_id=job_id,
        ).data
        rule, tables = _documents(draft, clause)
        errs, dry = validate(rule, tables, rulebase, clause.text)
        history.append(errs)
        if not errs:
            return CompileResult(
                True,
                rule,
                tables,
                [],
                dry,
                attempt,
                draft.get("notes", ""),
                history=history,
                draft=draft,
            )
        messages = [
            *messages,
            {"role": "assistant", "content": json.dumps(draft)},
            {
                "role": "user",
                "content": "The rule failed these checks:\n- "
                + "\n- ".join(errs)
                + "\nFix every problem and return the corrected rule.",
            },
        ]
    return CompileResult(
        False,
        rule,
        tables or [],
        history[-1],
        dry,
        len(history),
        draft.get("notes", ""),
        history=history,
        draft=draft,
    )


def validate(
    rule: dict[str, Any], tables: list[dict[str, Any]], rulebase: RuleBase, clause_text: str
) -> tuple[list[str], dict[str, dict[str, int]]]:
    """All deterministic checks. Returns (errors, dry-run status counts per fixture)."""
    errs: list[str] = []
    for t in tables:
        errs += [f"table {t['name']}: {e}" for e in schema_errors("table.schema.json", t)]
    errs += [f"rule: {e}" for e in schema_errors("rule.schema.json", rule)]
    if errs:
        return errs, {}

    all_tables = {**rulebase.tables, **{t["name"]: t for t in tables}}
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "draft.yaml"
        path.write_text(yaml.safe_dump(rule, sort_keys=False), encoding="utf-8")
        try:
            loaded = _load_rule(path, None, all_tables, Path(tmp))
        except RuleError as e:
            return [
                str(e).replace(str(path.relative_to(Path(tmp).parent).as_posix()) + ": ", "")
            ], {}

    cat = catalog()
    for name, compiled in loaded.exprs.items():
        for p in sorted(compiled.paths):
            if not cat.known(p, rule.get("for_each")):
                errs.append(f"{name} reads '{p}', which doesn't exist in the building model")
    errs += _number_problems(rule, tables, clause_text)

    dry: dict[str, dict[str, int]] = {}
    for name in FIXTURES:
        model = json.loads((REPO_ROOT / "fixtures" / "models" / f"{name}.json").read_text("utf-8"))
        counts: dict[str, int] = {}
        for r in evaluate(model, [loaded], all_tables):
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            if r["message"].startswith("Could not evaluate"):
                errs.append(f"dry run on {name}: {r['message']}")
        dry[name] = counts
    return sorted(set(errs), key=errs.index), dry


def save_draft(result: CompileResult, root: Path | None = None) -> Path:
    """Write the draft rule (and any new tables) under rules/drafts/ for human review."""
    assert result.rule is not None
    root = root or get_settings().rules_dir / "drafts"
    (root / "tables").mkdir(parents=True, exist_ok=True)
    for t in result.tables:
        (root / "tables" / f"{t['name'].split('.', 1)[1]}.yaml").write_text(
            yaml.safe_dump(t, sort_keys=False, allow_unicode=True), encoding="utf-8"
        )
    doc = dict(result.rule)
    if result.review:
        doc["review_notes"] = f"{result.review['verdict']}: " + " | ".join(result.review["notes"])
    path = root / f"{doc['id'].split('.', 2)[-1]}.yaml"
    path.write_text(
        yaml.safe_dump(doc, sort_keys=False, allow_unicode=True, width=100), encoding="utf-8"
    )
    return path


# ------------------------------------------------------------------ helpers


def _documents(
    draft: dict[str, Any], clause: Clause
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    clause_doc = {
        "ref": clause.ref,
        "excerpt": _excerpt(clause.text),
        "source": clause.source,
        "retrieved": datetime.now(UTC).date().isoformat(),
    }
    rule: dict[str, Any] = {
        "id": f"{clause.authority}.draft.{draft['slug']}",
        "title": draft["title"],
        "authority": clause.authority,
        "clause": clause_doc,
        "status": "draft",
        "severity": draft["severity"],
        "kind": draft["kind"],
    }
    for key in ("for_each", *EXPR_FIELDS):
        value = draft.get(key)
        if isinstance(value, str) and not value.strip():
            value = None
        if value is not None:
            rule[key] = value
    rule["message"] = draft["message"]
    if draft.get("fix_unit"):
        rule["fix_unit"] = draft["fix_unit"]
    rule["compiled_by"] = f"agent:{role('agent').model}@{version_tag('compiler')}"
    rule["freshness"] = {"status": "unchecked", "url": None, "checked": None}

    tables = []
    for t in draft.get("new_tables") or []:
        doc = {
            "name": f"{clause.authority}.{t['name']}",
            "authority": clause.authority,
            "description": t["description"],
            "unit": t.get("unit"),
            "source": clause_doc,
            "kind": t["kind"],
        }
        doc[t["kind"]] = t.get(t["kind"])
        tables.append(doc)
    return rule, tables


def _excerpt(text: str, limit: int = 400) -> str:
    flat = re.sub(r"\s+", " ", text).strip()
    return flat if len(flat) <= limit else flat[: limit - 1].rsplit(" ", 1)[0] + "…"


def _clause_numbers(text: str) -> set[float]:
    found = {float(n) for n in _NUMBER.findall(text)}
    allowed = set(found)
    for n in found:  # unit conversions: cm↔m, mm↔m, % → fraction
        allowed |= {round(n / 100, 6), round(n / 1000, 6), round(n * 100, 6)}
    return allowed


def _expr_numbers(source: str) -> set[float]:
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError:
        return set()
    return {
        float(n.value)
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant)
        and isinstance(n.value, (int, float))
        and not isinstance(n.value, bool)
    }


def _number_problems(
    rule: dict[str, Any], tables: list[dict[str, Any]], clause_text: str
) -> list[str]:
    allowed = _clause_numbers(clause_text) | TRIVIAL_NUMBERS
    used: set[float] = set()
    for key in EXPR_FIELDS:
        if rule.get(key):
            used |= _expr_numbers(rule[key])
    for t in tables:
        values = list((t.get("map") or {}).values()) + [
            x for b in (t.get("bands") or []) for x in (b["min"], b["max"], b["value"])
        ]
        used |= {
            float(v) for v in values if isinstance(v, (int, float)) and not isinstance(v, bool)
        }
    stray = sorted(n for n in used if round(n, 6) not in allowed)
    return [
        f"the number {n:g} does not appear in the clause text (no invented values)" for n in stray
    ]


def _describe_tables(rulebase: RuleBase) -> str:
    lines = []
    for name, t in sorted(rulebase.tables.items()):
        desc = (t.get("description") or "").split(". ")[0][:140]
        lines.append(f"- {name} ({t['kind']}, unit {t.get('unit')}): {desc}")
    return "\n".join(lines) or "(none)"


def _examples(rulebase: RuleBase) -> str:
    keep = (
        "title",
        "severity",
        "kind",
        "for_each",
        "applies_when",
        "limit",
        "measured",
        "check",
        "message",
        "fix_unit",
    )
    out = []
    for rid in EXAMPLE_RULES:
        if rid in rulebase.rules:
            doc = rulebase.rules[rid].doc
            out.append(
                yaml.safe_dump({k: doc[k] for k in keep if k in doc}, sort_keys=False, width=100)
            )
    return "\n---\n".join(out)


def _review(rule, tables, clause: Clause, llm: LLMClient, job_id) -> dict[str, Any]:
    body = yaml.safe_dump(
        {"rule": rule, "tables": tables}, sort_keys=False, allow_unicode=True, width=100
    )
    _, prompt = render(
        "review", clause_ref=clause.ref, clause_text=clause.text.strip(), rule_yaml=body
    )
    return llm.chat(
        "reviewer",
        [{"role": "user", "content": prompt}],
        schema=REVIEW_SCHEMA,
        reasoning=True,
        max_tokens=4000,
        purpose="review_rule",
        job_id=job_id,
    ).data


def parse_clause_file(path: Path) -> Clause:
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n(.*)$", text, re.DOTALL)
    if not m:
        raise ValueError(f"{path}: expected YAML front-matter (authority, clause_ref, source)")
    meta = yaml.safe_load(m.group(1))
    return Clause(
        text=m.group(2).strip(),
        ref=str(meta["clause_ref"]),
        source=meta["source"],
        authority=meta["authority"],
    )
