"""Rule and table loader.

Layout under rules/:
  <ruleset>/*.yaml              one rule per file           (e.g. rules/udcpr2020/stair-width.yaml)
  <ruleset>/tables/*.yaml       lookup tables
  cities/<ruleset>/...          same, for a city layer      (e.g. rules/cities/pmc/)
  drafts/*.yaml                 rule-compiler output, loaded only with include_drafts=True

Loading fails fast: any rule bug raises RuleError naming the file. Nothing half-loaded is returned.
"""

from __future__ import annotations

import hashlib
import string
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from compliance.config import get_settings
from compliance.engine.derived import inputs_for
from compliance.engine.expr import Compiled, ExprError, compile_expr
from compliance.schemas import errors, load_yaml

EXPR_FIELDS = ("applies_when", "limit", "measured", "check")
MESSAGE_FIELDS = frozenset({"measured", "limit"})
NOT_RULES = frozenset({"authority.yaml"})


class RuleError(Exception):
    """A rule or table file is invalid. The message starts with the file path."""


@dataclass(frozen=True)
class LoadedRule:
    doc: dict[str, Any]
    file: Path
    ruleset: str
    exprs: dict[str, Compiled]  # applies_when / limit / measured / check, when present
    requires: frozenset[str]  # model input paths, e.g. 'site.edges[*].road_width_m'

    @property
    def id(self) -> str:
        return self.doc["id"]

    @property
    def kind(self) -> str:
        return self.doc.get("kind", "check")

    @property
    def for_each(self) -> str | None:
        return self.doc.get("for_each")


@dataclass(frozen=True)
class RuleBase:
    rules: dict[str, LoadedRule]
    tables: dict[str, dict[str, Any]]
    version: str

    def select(self, rulesets: list[str]) -> list[LoadedRule]:
        """Rules for a project using `rulesets` (ordered), minus rules overridden by another one."""
        chosen = [r for r in self.rules.values() if r.ruleset in rulesets]
        overridden = {r.doc.get("overrides") for r in chosen} - {None}
        chosen = [r for r in chosen if r.id not in overridden]
        return sorted(chosen, key=lambda r: (rulesets.index(r.ruleset), r.id))


def load_rulebase(root: Path | None = None, *, include_drafts: bool = False) -> RuleBase:
    root = root or get_settings().rules_dir
    rule_files: list[tuple[str | None, Path]] = []
    table_files: list[Path] = []
    for ruleset, folder in _ruleset_dirs(root):
        rule_files += [
            (ruleset, p) for p in sorted(folder.glob("*.yaml")) if p.name not in NOT_RULES
        ]
        table_files += sorted((folder / "tables").glob("*.yaml"))
    if include_drafts:
        rule_files += [(None, p) for p in sorted((root / "drafts").glob("*.yaml"))]
        table_files += sorted((root / "drafts" / "tables").glob("*.yaml"))

    tables: dict[str, dict[str, Any]] = {}
    for path in table_files:
        doc = _read(path, "table.schema.json", root)
        if doc["name"] in tables:
            raise RuleError(f"{_rel(path, root)}: duplicate table name '{doc['name']}'")
        tables[doc["name"]] = doc

    rules: dict[str, LoadedRule] = {}
    for ruleset, path in rule_files:
        rule = _load_rule(path, ruleset, tables, root)
        if rule.id in rules:
            other = _rel(rules[rule.id].file, root)
            raise RuleError(f"{_rel(path, root)}: duplicate rule id '{rule.id}' (also in {other})")
        rules[rule.id] = rule

    for rule in rules.values():
        target = rule.doc.get("overrides")
        if target is not None and target not in rules:
            raise RuleError(f"{_rel(rule.file, root)}: overrides unknown rule '{target}'")

    files = sorted([p for _, p in rule_files] + table_files)
    digest = hashlib.sha256()
    for p in files:
        digest.update(_rel(p, root).encode())
        digest.update(p.read_bytes())
    return RuleBase(rules=rules, tables=tables, version=digest.hexdigest()[:12])


# --------------------------------------------------------------------------- helpers


def _ruleset_dirs(root: Path) -> list[tuple[str, Path]]:
    out = []
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if d.name == "drafts":
            continue
        if d.name == "cities":
            out += [(c.name, c) for c in sorted(p for p in d.iterdir() if p.is_dir())]
        else:
            out.append((d.name, d))
    return out


def _rel(path: Path, root: Path) -> str:
    try:
        return path.relative_to(root.parent).as_posix()
    except ValueError:
        return path.as_posix()


def _read(path: Path, schema: str, root: Path) -> dict[str, Any]:
    try:
        doc = load_yaml(path.read_text(encoding="utf-8"))
    except Exception as e:  # noqa: BLE001 - any YAML problem is a rule-file bug
        raise RuleError(f"{_rel(path, root)}: not valid YAML: {e}") from None
    if not isinstance(doc, dict):
        raise RuleError(f"{_rel(path, root)}: expected a mapping at the top level")
    errs = errors(schema, doc)
    if errs:
        raise RuleError(f"{_rel(path, root)}: does not match {schema}: " + "; ".join(errs))
    return doc


def _load_rule(path: Path, ruleset: str | None, tables: dict[str, Any], root: Path) -> LoadedRule:
    where = _rel(path, root)
    doc = _read(path, "rule.schema.json", root)
    if ruleset is not None and doc["authority"] != ruleset:
        raise RuleError(f"{where}: authority '{doc['authority']}' doesn't match folder '{ruleset}'")
    ruleset = ruleset or doc["authority"]

    exprs: dict[str, Compiled] = {}
    for name in EXPR_FIELDS:
        if doc.get(name) is None:
            continue
        try:
            exprs[name] = compile_expr(doc[name])
        except ExprError as e:
            raise RuleError(f"{where}: {name}: {e}") from None

    for name, c in exprs.items():
        roots = {p.split(".", 1)[0].split("[", 1)[0] for p in c.paths}
        if "item" in roots and not doc.get("for_each"):
            raise RuleError(f"{where}: {name} uses 'item' but the rule has no for_each")
        for named in ("limit", "measured"):
            if named in roots:
                if name in ("limit", "measured"):
                    raise RuleError(f"{where}: {name} can't refer to '{named}'")
                if named not in exprs:
                    raise RuleError(
                        f"{where}: {name} uses '{named}' but the rule doesn't define it"
                    )
        for t in c.tables:
            if t not in tables:
                raise RuleError(f"{where}: {name} uses unknown table '{t}'")

    fields = {f for _, f, _, _ in string.Formatter().parse(doc["message"]) if f}
    bad = {f.split(".", 1)[0].split("[", 1)[0] for f in fields} - MESSAGE_FIELDS
    if bad:
        raise RuleError(f"{where}: message may only use {{measured}} and {{limit}}, not {bad}")
    for f in fields & MESSAGE_FIELDS:
        if f not in exprs:
            raise RuleError(f"{where}: message uses {{{f}}} but the rule doesn't define {f}")

    return LoadedRule(doc, path, ruleset, exprs, _requires(exprs, doc.get("for_each")))


def _requires(exprs: dict[str, Compiled], for_each: str | None) -> frozenset[str]:
    out: set[str] = set()
    for c in exprs.values():
        for p in c.paths:
            head = p.split(".", 1)[0]
            if head in ("limit", "measured"):
                continue
            if head == "item":
                p = f"{for_each}[*]{p[len('item') :]}"
            out.update(inputs_for(p))
    return frozenset(out)
