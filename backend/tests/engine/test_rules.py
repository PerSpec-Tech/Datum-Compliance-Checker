"""rule and table loader."""

import copy

import pytest
import yaml

from compliance.config import get_settings
from compliance.engine.rules import RuleError, load_rulebase

CLAUSE = {
    "ref": "9.29.1",
    "excerpt": "No exit doorway shall be less than 90 cm.",
    "source": "x p.1",
}
RULE = {
    "id": "udcpr2020.ch9.exit-door-width",
    "title": "Minimum width of exit doors",
    "authority": "udcpr2020",
    "clause": CLAUSE,
    "status": "draft",
    "severity": "major",
    "for_each": "doors",
    "applies_when": "item.is_exit",
    "limit": "table('udcpr2020.min_exit_door', 'default')",
    "measured": "item.width_m",
    "check": "measured >= limit",
    "message": "Exit door is {measured:.2f} m wide; minimum is {limit:.2f} m.",
    "compiled_by": "human",
}
TABLE = {
    "name": "udcpr2020.min_exit_door",
    "authority": "udcpr2020",
    "kind": "map",
    "map": {"default": 0.9},
    "source": CLAUSE,
}
FAR_RULE = {
    "id": "pmc.tod.max-fsi",
    "title": "Maximum FSI in TOD zone",
    "authority": "pmc",
    "clause": CLAUSE,
    "status": "draft",
    "severity": "critical",
    "applies_when": "project.overlays.metro_tod",
    "measured": "derived.far",
    "limit": "2.5",
    "check": "measured <= limit",
    "message": "FSI {measured:.2f} exceeds {limit:.2f}.",
    "compiled_by": "human",
}


def write(path, doc):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")


@pytest.fixture
def tree(tmp_path):
    root = tmp_path / "rules"
    write(root / "udcpr2020" / "exit-door.yaml", RULE)
    write(root / "udcpr2020" / "tables" / "min-exit-door.yaml", TABLE)
    write(root / "cities" / "pmc" / "tod-fsi.yaml", FAR_RULE)
    write(root / "cities" / "pmc" / "authority.yaml", {"id": "pmc"})  # not a rule
    write(root / "cities" / "pmc" / "data" / "x.yaml", {"anything": 1})  # not a rule
    return root


def test_loads_rules_and_tables(tree):
    rb = load_rulebase(tree)
    assert set(rb.rules) == {RULE["id"], FAR_RULE["id"]}
    assert set(rb.tables) == {TABLE["name"]}
    assert rb.rules[FAR_RULE["id"]].ruleset == "pmc"
    assert len(rb.version) == 12


def test_requires_expands_item_and_derived_paths(tree):
    rb = load_rulebase(tree)
    assert rb.rules[RULE["id"]].requires == {"doors[*].is_exit", "doors[*].width_m"}
    assert {"project.overlays.metro_tod", "site.plot_area_declared_m2"} <= rb.rules[
        FAR_RULE["id"]
    ].requires


def test_dates_stay_strings(tree):
    doc = dict(RULE, clause={**CLAUSE, "retrieved": "2026-10-14"})
    (tree / "udcpr2020" / "exit-door.yaml").write_text(
        yaml.safe_dump(doc).replace("'2026-10-14'", "2026-10-14"), encoding="utf-8"
    )
    assert load_rulebase(tree).rules[RULE["id"]].doc["clause"]["retrieved"] == "2026-10-14"


def test_version_changes_when_a_file_changes(tree):
    v1 = load_rulebase(tree).version
    write(tree / "udcpr2020" / "tables" / "min-exit-door.yaml", {**TABLE, "map": {"default": 1.0}})
    assert load_rulebase(tree).version != v1


def test_select_orders_by_ruleset_and_drops_overridden(tree):
    write(
        tree / "cities" / "pmc" / "door.yaml",
        {**RULE, "id": "pmc.door", "authority": "pmc", "overrides": RULE["id"]},
    )
    rb = load_rulebase(tree)
    assert [r.id for r in rb.select(["udcpr2020", "pmc"])] == ["pmc.door", "pmc.tod.max-fsi"]
    assert [r.id for r in rb.select(["udcpr2020"])] == [RULE["id"]]


def test_drafts_only_when_asked(tree):
    write(tree / "drafts" / "d.yaml", {**RULE, "id": "udcpr2020.draft.x"})
    assert "udcpr2020.draft.x" not in load_rulebase(tree).rules
    assert "udcpr2020.draft.x" in load_rulebase(tree, include_drafts=True).rules


def mutate(**changes):
    doc = copy.deepcopy(RULE)
    for k, v in changes.items():
        if v is None:
            doc.pop(k, None)
        else:
            doc[k] = v
    return doc


@pytest.mark.parametrize(
    ("doc", "match"),
    [
        (mutate(severity="huge"), "does not match rule.schema.json"),
        (mutate(check="item.__class__"), "check: attribute '__class__'"),
        (mutate(check="measured >= limit +"), "check: syntax error"),
        (mutate(for_each=None), "uses 'item' but the rule has no for_each"),
        (mutate(limit=None, message="Door {measured}"), "uses 'limit' but the rule doesn't define"),
        (mutate(limit="table('nope', 1)"), "unknown table 'nope'"),
        (mutate(message="Door {item.width_m}"), "message may only use"),
        (mutate(measured=None, message="{measured}", check="item.width_m > 1"), "message uses"),
        (mutate(limit="measured * 2"), "limit can't refer to 'measured'"),
        (mutate(authority="pmc"), "doesn't match folder"),
        (mutate(overrides="ghost.rule"), "overrides unknown rule"),
    ],
)
def test_rule_bugs_fail_fast_naming_the_file(tree, doc, match):
    write(tree / "udcpr2020" / "exit-door.yaml", doc)
    with pytest.raises(RuleError, match=match) as e:
        load_rulebase(tree)
    assert "rules/udcpr2020/exit-door.yaml" in str(e.value)


def test_duplicate_ids_fail(tree):
    write(tree / "udcpr2020" / "copy.yaml", RULE)
    with pytest.raises(RuleError, match="duplicate rule id"):
        load_rulebase(tree)


def test_bad_yaml_fails(tree):
    (tree / "udcpr2020" / "broken.yaml").write_text("id: [unclosed", encoding="utf-8")
    with pytest.raises(RuleError, match="not valid YAML"):
        load_rulebase(tree)


def test_real_rules_folder_loads():
    load_rulebase(get_settings().rules_dir)  # must not raise, whatever rules exist so far
