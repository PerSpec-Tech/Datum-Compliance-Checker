"""What rule expressions may read: every attribute path, generated from the BuildingModel schema
(so it can't drift from the contract) plus the derived values. Used by the rule compiler to
reject expressions that read fields which don't exist, and to tell the model what it can use.
"""

from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from typing import Any

from compliance.engine.derived import INPUTS
from compliance.schemas import registry

COLLECTIONS = ("levels", "spaces", "areas", "stairs", "doors", "units", "site.edges")


@dataclass(frozen=True)
class Catalog:
    roots: frozenset[str]  # e.g. project.zone, project.occupancy.group, site.plot_area_declared_m2
    items: dict[str, frozenset[str]]  # collection → item fields, e.g. doors → {width_m, is_exit, …}
    derived: frozenset[str]  # derived.<name>

    def known(self, path: str, for_each: str | None) -> bool:
        head = path.split(".", 1)[0]
        if head in ("limit", "measured"):
            return True
        if head == "item":
            if for_each is None:
                return False
            rest = path[len("item") :].lstrip(".")
            fields = self.items.get(for_each, frozenset())
            return rest == "" or rest in fields or any(f.startswith(rest + ".") for f in fields)
        if head == "derived":
            name = path.split(".")[1] if "." in path else ""
            return path == "derived" or f"derived.{name}" in self.derived
        if head in COLLECTIONS or path in COLLECTIONS:
            return True
        return path in self.roots or any(r.startswith(path + ".") for r in self.roots)

    def describe(self) -> str:
        """Compact listing for the compiler prompt."""
        lines = ["Project and site (single values):"]
        lines += [f"  {p}" for p in sorted(self.roots)]
        lines.append("Collections (use with for_each; fields are read as item.<field>):")
        for coll, fields in self.items.items():
            lines.append(f"  {coll}: " + ", ".join(sorted(fields)))
        lines.append("Derived values (computed from geometry):")
        lines += [f"  {d}" for d in sorted(self.derived)]
        return "\n".join(lines)


@lru_cache
def catalog() -> Catalog:
    reg = registry()
    model = reg.contents("building-model.schema.json")

    def resolve(node: dict[str, Any], base: str) -> tuple[dict[str, Any], str, str | None]:
        """(schema, base file, ref name) after following $ref / anyOf-with-null."""
        name = None
        while True:
            if "$ref" in node:
                ref = node["$ref"]
                file, _, pointer = ref.partition("#")
                file = file or base
                name = pointer.rsplit("/", 1)[-1]
                node = reg.contents(file)
                for part in pointer.strip("/").split("/"):
                    node = node[part]
                base = file
                continue
            if "anyOf" in node:
                non_null = [n for n in node["anyOf"] if n.get("type") != "null"]
                if len(non_null) == 1:
                    node = non_null[0]
                    continue
            return node, base, name

    roots: set[str] = set()
    items: dict[str, set[str]] = {}

    def walk(node: dict[str, Any], base: str, prefix: str, into: set[str]) -> None:
        node, base, name = resolve(node, base)
        if name and name.startswith("Fact"):  # facts unwrap to their value
            into.add(prefix)
            value, vbase, _ = resolve(node["properties"]["value"], base)
            if value.get("type") == "object" or "properties" in value:
                for k, sub in value.get("properties", {}).items():
                    walk(sub, vbase, f"{prefix}.{k}", into)
            return
        if node.get("type") == "array" or (
            isinstance(node.get("type"), list) and "array" in node["type"]
        ):
            into.add(prefix)
            item, ibase, _ = resolve(node.get("items", {}), base)
            if "properties" in item and prefix.split(".")[-1] in {
                c.split(".")[-1] for c in COLLECTIONS
            }:
                fields: set[str] = set()
                for k, sub in item["properties"].items():
                    walk(sub, ibase, k, fields)
                items[prefix] = fields
            return
        if "properties" in node:
            if prefix:
                into.add(prefix)
            for k, sub in node["properties"].items():
                if k.startswith("_") or k in ("schema_version", "meta"):
                    continue
                walk(sub, base, f"{prefix}.{k}" if prefix else k, into)
            return
        into.add(prefix)

    walk(model, "building-model.schema.json", "", roots)
    roots -= set(COLLECTIONS)
    roots = {
        r
        for r in roots
        if r.split(".", 1)[0] not in ("levels", "spaces", "areas", "stairs", "doors", "units")
    }
    roots = {r for r in roots if not r.startswith("site.edges")}
    derived = frozenset(f"derived.{n}" for n in INPUTS)
    return Catalog(frozenset(roots), {k: frozenset(v) for k, v in items.items()}, derived)
