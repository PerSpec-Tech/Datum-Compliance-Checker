"""P1.6: the fixtures match the contracts, and the validator rejects bad data."""

import copy
import json
import sys

import pytest
from jsonschema import ValidationError

from compliance.config import REPO_ROOT
from compliance.models.generated.building_model_schema import BuildingModel

sys.path.insert(0, str(REPO_ROOT / "scripts"))
import validate  # noqa: E402

FIXTURES = sorted((REPO_ROOT / "fixtures" / "models").glob("*.json"))


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_there_are_three_fixtures():
    assert {p.stem for p in FIXTURES} >= {"compliant_house", "violating_apartment", "missing_site"}


@pytest.mark.parametrize("path", FIXTURES, ids=lambda p: p.stem)
def test_fixture_loads_into_generated_pydantic_model(path):
    model = BuildingModel.model_validate(load(path))
    assert model.schema_version == "1.0"


def test_violating_apartment_lists_at_least_six_failures():
    notes = load(REPO_ROOT / "fixtures/models/violating_apartment.json")["_notes"]
    assert sum(1 for n in notes if n.startswith("F")) >= 6


def test_missing_site_has_no_site_context():
    doc = load(REPO_ROOT / "fixtures/models/missing_site.json")
    assert doc["site"]["boundary"] is None
    assert doc["site"]["edges"] == []


@pytest.mark.parametrize(
    "mutate",
    [
        lambda d: d["project"]["location"].update(source="guessed"),  # bad Source enum
        lambda d: d["stairs"][0].pop("riser_m"),  # missing required field
        lambda d: d["site"].update(boundary=[[0, 0], [1, 1]]),  # polygon needs ≥ 3 points
        lambda d: d.update(extra_field=1),  # additionalProperties: false
    ],
    ids=["bad-source", "missing-field", "short-polygon", "unknown-field"],
)
def test_validator_rejects_bad_models(mutate):
    doc = copy.deepcopy(load(REPO_ROOT / "fixtures/models/compliant_house.json"))
    mutate(doc)
    with pytest.raises(ValidationError):
        validate.validator("building-model.schema.json").validate(doc)
