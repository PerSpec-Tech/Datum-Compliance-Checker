"""JSON Schema validators for schemas/ (shared by the engine and scripts/validate.py)."""

from __future__ import annotations

import json
from functools import lru_cache

import yaml
from jsonschema import Draft202012Validator, FormatChecker
from referencing import Registry, Resource
from referencing.jsonschema import DRAFT202012

from compliance.config import get_settings

SCHEMA_FILES = (
    "common.schema.json",
    "building-model.schema.json",
    "rule.schema.json",
    "table.schema.json",
    "check-report.schema.json",
)


@lru_cache
def registry() -> Registry:
    root = get_settings().schemas_dir
    resources = []
    for name in SCHEMA_FILES:
        contents = json.loads((root / name).read_text(encoding="utf-8"))
        resource = Resource.from_contents(contents, default_specification=DRAFT202012)
        resources.append((name, resource))
    return Registry().with_resources(resources)


@lru_cache
def validator(schema_name: str) -> Draft202012Validator:
    reg = registry()
    return Draft202012Validator(
        reg.contents(schema_name), registry=reg, format_checker=FormatChecker()
    )


def errors(schema_name: str, doc: object, limit: int = 10) -> list[str]:
    """Human-readable validation errors ('at <path>: <message>'), empty when valid."""
    out = []
    for e in sorted(validator(schema_name).iter_errors(doc), key=lambda e: list(e.absolute_path)):
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        out.append(f"at {where}: {e.message[:300]}")
        if len(out) >= limit:
            break
    return out


class _StringDateLoader(yaml.SafeLoader):
    """SafeLoader that keeps dates as strings, so `retrieved: 2026-10-14` matches format: date."""


_StringDateLoader.yaml_implicit_resolvers = {
    ch: [(tag, rx) for tag, rx in resolvers if tag != "tag:yaml.org,2002:timestamp"]
    for ch, resolvers in yaml.SafeLoader.yaml_implicit_resolvers.items()
}


def load_yaml(text: str) -> object:
    return yaml.load(text, Loader=_StringDateLoader)  # noqa: S506 - SafeLoader subclass
