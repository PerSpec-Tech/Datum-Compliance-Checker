"""Validate JSON/YAML files against the contracts in schemas/.

Usage:
  just validate <file>        validate one file; the schema is picked from its path
  just validate-fixtures      check every schema, then every fixture, rule and table
  scripts/validate.py --schemas   only check the schemas are valid and their $refs resolve

Schema by path: fixtures/models/*.json → building-model · *.report.json → check-report ·
rules/**/tables/*.yaml → table · other rules/**/*.yaml → rule.
"""

import json
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

from compliance.config import REPO_ROOT
from compliance.schemas import SCHEMA_FILES, load_yaml, registry, validator

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def load(path: Path):
    text = path.read_text(encoding="utf-8")
    return load_yaml(text) if path.suffix in (".yaml", ".yml") else json.loads(text)


def schema_for(path: Path) -> str | None:
    p = path.resolve().as_posix()
    if p.endswith(".report.json"):
        return "check-report.schema.json"
    if ("/fixtures/models/" in p or "/revit-addin/tests/out/" in p) and path.suffix == ".json":
        return "building-model.schema.json"
    if "/rules/" in p and path.suffix in (".yaml", ".yml"):
        if "/data/" in p or path.name == "authority.yaml":
            return None
        return "table.schema.json" if "/tables/" in p else "rule.schema.json"
    return None


def check_schemas() -> int:
    errors = 0
    reg = registry()
    for name in SCHEMA_FILES:
        schema = reg.contents(name)
        try:
            Draft202012Validator.check_schema(schema)
            # Resolve every $ref so a typo in a cross-file reference fails here, not at codegen.
            res = reg.resolver(name)
            for ref in sorted(_refs(schema)):
                res.lookup(ref)
            print(f"schema ok   {name}")
        except Exception as e:  # noqa: BLE001
            errors += 1
            print(f"schema FAIL {name}: {e}")
    return errors


def _refs(node) -> set[str]:
    out: set[str] = set()
    if isinstance(node, dict):
        if isinstance(node.get("$ref"), str):
            out.add(node["$ref"])
        for v in node.values():
            out |= _refs(v)
    elif isinstance(node, list):
        for v in node:
            out |= _refs(v)
    return out


def validate_file(path: Path) -> int:
    name = schema_for(path)
    if name is None:
        print(f"skip        {path.relative_to(REPO_ROOT).as_posix()} (no schema for this path)")
        return 0
    errs = sorted(validator(name).iter_errors(load(path)), key=lambda e: list(e.absolute_path))
    rel = path.relative_to(REPO_ROOT).as_posix()
    if not errs:
        print(f"ok          {rel}  [{name}]")
        return 0
    print(f"FAIL        {rel}  [{name}]")
    for e in errs[:20]:
        where = "/".join(str(p) for p in e.absolute_path) or "(root)"
        print(f"    at {where}: {e.message[:300]}")
    if len(errs) > 20:
        print(f"    … {len(errs) - 20} more")
    return len(errs)


def main() -> int:
    args = sys.argv[1:]
    if args == ["--schemas"]:
        return 1 if check_schemas() else 0
    if args == ["--fixtures"]:
        errors = check_schemas()
        files = sorted((REPO_ROOT / "fixtures" / "models").glob("*.json"))
        files += sorted((REPO_ROOT / "fixtures" / "expected").glob("*.report.json"))
        files += sorted(p for p in (REPO_ROOT / "rules").rglob("*.yaml") if schema_for(p))
        for f in files:
            errors += validate_file(f)
        print(f"\n{len(files)} files checked, {errors} errors")
        return 1 if errors else 0
    if len(args) == 1:
        path = Path(args[0])
        path = path if path.is_absolute() else (Path.cwd() / path)
        return 1 if validate_file(path.resolve()) else 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main())
