"""P1.5: generate Python, TypeScript and C# types from schemas/ (D10). Run with `just codegen`.

Outputs (never edit by hand; re-run this instead):
  backend/src/compliance/models/generated/   pydantic v2 (datamodel-codegen)
  web/src/generated/contracts.ts             TypeScript (quicktype)
  revit-addin/src/ComplianceChecker/Generated/Contracts.cs   C# System.Text.Json (quicktype)
"""

import shutil
import subprocess
import sys

from compliance.config import REPO_ROOT

QUICKTYPE = "quicktype@23.3.25"  # pinned so output is reproducible
SCHEMAS = REPO_ROOT / "schemas"
# Top-level contracts; common.schema.json is pulled in through $refs.
TOP_LEVEL = [
    "building-model.schema.json",
    "rule.schema.json",
    "table.schema.json",
    "check-report.schema.json",
]
PY_OUT = REPO_ROOT / "backend" / "src" / "compliance" / "models" / "generated"
TS_OUT = REPO_ROOT / "web" / "src" / "generated" / "contracts.ts"
CS_OUT = REPO_ROOT / "revit-addin" / "src" / "ComplianceChecker" / "Generated" / "Contracts.cs"
HEADER = "GENERATED — DO NOT EDIT. Source: schemas/*.schema.json. Regenerate with `just codegen`."


def run(cmd: list[str]) -> None:
    print("$", " ".join(cmd))
    exe = shutil.which(cmd[0]) or cmd[0]
    subprocess.run([exe, *cmd[1:]], check=True, cwd=REPO_ROOT)


def python() -> None:
    if PY_OUT.exists():
        shutil.rmtree(PY_OUT)
    run(
        [
            sys.executable,
            "-m",
            "datamodel_code_generator",
            "--input",
            str(SCHEMAS),
            "--input-file-type",
            "jsonschema",
            "--output",
            str(PY_OUT),
            "--output-model-type",
            "pydantic_v2.BaseModel",
            "--target-python-version",
            "3.12",
            "--use-title-as-name",
            "--use-schema-description",
            "--field-constraints",
            "--use-double-quotes",
            "--disable-timestamp",
            "--custom-file-header",
            f"# {HEADER}",
        ]
    )


def quicktype(lang_args: list[str], out) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    # quicktype misreads absolute Windows paths ("D:\...") as URLs, so pass repo-relative paths.
    rel = lambda p: p.relative_to(REPO_ROOT).as_posix()  # noqa: E731
    srcs = [rel(SCHEMAS / name) for name in TOP_LEVEL]
    run(["npx", "--yes", QUICKTYPE, "--src-lang", "schema", *lang_args, "-o", rel(out), *srcs])
    body = out.read_text(encoding="utf-8")
    out.write_text(f"// {HEADER}\n{body}", encoding="utf-8", newline="\n")


def main() -> int:
    python()
    quicktype(["--lang", "ts", "--just-types", "--prefer-unions"], TS_OUT)
    quicktype(
        [
            "--lang",
            "cs",
            "--framework",
            "SystemTextJson",
            "--namespace",
            "ComplianceChecker.Generated",
            "--array-type",
            "list",
            "--csharp-version",
            "6",
        ],
        CS_OUT,
    )
    for f in [*sorted(PY_OUT.glob("*.py")), TS_OUT, CS_OUT]:
        print(f"wrote {f.relative_to(REPO_ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
