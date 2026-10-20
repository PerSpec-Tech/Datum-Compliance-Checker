"""P2.7: golden reports. Any change in engine output or rules shows up as a diff here.

Regenerate with `just test-backend --update-golden`, then review the diff before keeping it.
"""

import json

import pytest

from compliance.config import REPO_ROOT
from compliance.engine.report import build_report
from compliance.engine.rules import load_rulebase
from compliance.schemas import errors

MODELS = REPO_ROOT / "fixtures" / "models"
EXPECTED = REPO_ROOT / "fixtures" / "expected"
VOLATILE = ("id", "created_at", "ruleset_version")  # change on every run / every rule edit
NAMES = ["compliant_house", "violating_apartment", "missing_site", "demo_apartment", "demo_house"]


def stable(report):
    return {k: v for k, v in report.items() if k not in VOLATILE}


@pytest.fixture(scope="module")
def rulebase():
    return load_rulebase()


@pytest.mark.parametrize("name", NAMES)
def test_golden_report(name, rulebase, request):
    model = json.loads((MODELS / f"{name}.json").read_text("utf-8"))
    report = build_report(model, rulebase, project_id=f"fixture-{name}", model_version="fixture")
    assert errors("check-report.schema.json", report) == []

    path = EXPECTED / f"{name}.report.json"
    if request.config.getoption("--update-golden") or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        body = {
            **report,
            # Fixed, schema-valid placeholders (C# parses these files too).
            "id": "volatile",
            "created_at": "2000-01-01T00:00:00+00:00",
            "ruleset_version": "volatile",
        }
        path.write_text(json.dumps(body, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        pytest.skip(f"wrote {path.name}; review the diff and re-run")

    expected = json.loads(path.read_text("utf-8"))
    assert stable(report) == stable(expected)
