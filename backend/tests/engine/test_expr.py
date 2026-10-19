"""P2.1: safe expression evaluator."""

import pytest

from compliance.engine.expr import ExprError, compile_expr


def F(value, source="declared"):
    return {"value": value, "source": source}


CTX = {
    "project": {"zone": F("residential"), "occupancy": F({"group": "A", "subdivision": "A-4"})},
    "site": {
        "plot_area_declared_m2": F(1000.0),
        "edges": [
            {"id": "e1", "kind": F("road"), "road_width_m": F(10.5)},
            {"id": "e2", "kind": F("neighbour"), "road_width_m": F(None, "default")},
        ],
    },
    "derived": {"far": 3.2, "setback_m": {"e1": 6.0}, "building_height_m": 14.75},
    "units": [
        {"id": "U1", "carpet_area_m2": 22.0},
        {"id": "U2", "carpet_area_m2": 80.0},
        {"id": "U3", "carpet_area_m2": None},
    ],
    "doors": [{"id": "D1", "width_m": 0.85, "is_exit": F(True)}],
    "limit": 2.5,
    "measured": 3.2,
}
TABLES = {
    "pmc.tod_max_fsi": {
        "kind": "bands",
        "bands": [
            {"min": 9.0, "max": 12.0, "value": 2.5},
            {"min": 12.0, "max": 15.0, "value": 3.0},
            {"min": 24.0, "max": None, "value": 4.0},
        ],
    },
    "udcpr.stair_width": {"kind": "map", "map": {"A-4": 1.0, "A-2": 0.75}},
    "udcpr.margin": {
        "kind": "map_of_bands",
        "map_of_bands": {"residential": [{"min": 0, "max": None, "value": 3.0}]},
    },
}


def ev(src, ctx=CTX, **kw):
    return compile_expr(src).eval(ctx, tables=TABLES, **kw)


# ---------------------------------------------------------------- basics


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("1 + 2 * 3", 7),
        ("(10 - 4) / 4", 1.5),
        ("7 // 2 + 7 % 2", 4),
        ("2 ** 3", 8),
        ("-derived.far", -3.2),
        ("measured > limit", True),
        ("1 < 2 < 3", True),
        ("1 < 3 < 2", False),
        ("project.zone == 'residential'", True),
        ("project.zone in ['commercial', 'residential']", True),
        ("project.zone not in ('commercial',)", True),
        ("'big' if derived.far > 3 else 'small'", "big"),
        ("not (derived.far > 3)", False),
        ("min(1, 2, 0.5)", 0.5),
        ("max(derived.far, limit)", 3.2),
        ("abs(-2)", 2),
        ("round(3.14159, 2)", 3.14),
        ("len(units)", 3),
        ("between(derived.building_height_m, 0, 15)", True),
        ("derived.setback_m['e1']", 6.0),
        ("site.edges['e1'].road_width_m", 10.5),
        ("site.edges[0].road_width_m", 10.5),
        ("project.occupancy.subdivision", "A-4"),
    ],
)
def test_evaluates(src, expected):
    r = ev(src)
    assert not r.is_missing
    if isinstance(expected, float):
        assert r.value == pytest.approx(expected)
    else:
        assert r.value == expected


def test_named_limit_and_measured_are_plain_roots():
    assert ev("measured - limit").value == pytest.approx(0.7)


# ---------------------------------------------------------------- tables


@pytest.mark.parametrize(
    ("src", "expected"),
    [
        ("table('pmc.tod_max_fsi', 10.5)", 2.5),
        ("table('pmc.tod_max_fsi', 12)", 3.0),  # min inclusive, max exclusive
        ("table('pmc.tod_max_fsi', 30)", 4.0),  # open-ended top band
        ("table('udcpr.stair_width', project.occupancy.subdivision)", 1.0),
        ("table('udcpr.margin', project.zone, 10.5)", 3.0),
        ("derived.far <= table('pmc.tod_max_fsi', site.edges['e1'].road_width_m)", False),
    ],
)
def test_tables(src, expected):
    assert ev(src).value == expected


def test_table_gap_is_missing_not_an_error():
    r = ev("table('pmc.tod_max_fsi', 20)")  # 15–24 band not in this table
    assert r.is_missing and r.missing == {"table:pmc.tod_max_fsi[20]"}


def test_unknown_table_is_an_error():
    with pytest.raises(ExprError, match="unknown table"):
        ev("table('nope', 1)")


def test_static_table_names():
    assert compile_expr("table('pmc.tod_max_fsi', 1) + table('udcpr.stair_width', 'A')").tables == {
        "pmc.tod_max_fsi",
        "udcpr.stair_width",
    }


# ---------------------------------------------------------------- facts and missing values


def test_facts_are_unwrapped_and_recorded():
    r = ev("site.edges['e1'].road_width_m >= 12")
    assert r.value is False
    assert [(f.path, f.value, f.source) for f in r.facts] == [
        ("site.edges[e1].road_width_m", 10.5, "declared")
    ]


def test_null_fact_makes_result_missing_with_path():
    r = ev("site.edges['e2'].road_width_m >= 12")
    assert r.is_missing and r.value is None
    assert r.missing == {"site.edges[e2].road_width_m"}


def test_missing_propagates_through_arithmetic_and_calls():
    r = ev("max(site.edges['e2'].road_width_m * 2, 1)")
    assert r.missing == {"site.edges[e2].road_width_m"}


def test_missing_key_in_derived_dict_is_missing():
    assert ev("derived.setback_m['e9'] > 3").missing == {"derived.setback_m[e9]"}


@pytest.mark.parametrize(
    ("src", "value", "missing"),
    [
        # False and ? → False · True or ? → True · True and ? → ? · False or ? → ?
        ("derived.far > 99 and site.edges['e2'].road_width_m > 0", False, False),
        ("derived.far > 1 or site.edges['e2'].road_width_m > 0", True, False),
        ("derived.far > 1 and site.edges['e2'].road_width_m > 0", None, True),
        ("derived.far > 99 or site.edges['e2'].road_width_m > 0", None, True),
        ("not site.edges['e2'].road_width_m", None, True),
        ("1 if site.edges['e2'].road_width_m else 2", None, True),
    ],
)
def test_three_valued_logic(src, value, missing):
    r = ev(src)
    assert r.value == value and r.is_missing == missing


def test_label_renames_item_paths():
    ctx = {**CTX, "item": {"id": "D1", "width_m": None}}
    r = ev("item.width_m >= 0.9", ctx=ctx, labels={"item": "doors[D1]"})
    assert r.missing == {"doors[D1].width_m"}


# ---------------------------------------------------------------- count / any / all


def test_count_with_known_values():
    ctx = {**CTX, "units": CTX["units"][:2]}
    assert ev("count(units, 'item.carpet_area_m2 < 25')", ctx=ctx).value == 1


def test_count_with_a_missing_element_is_missing():
    r = ev("count(units, 'item.carpet_area_m2 < 25')")
    assert r.missing == {"units[U3].carpet_area_m2"}


def test_count_static_paths_are_prefixed():
    c = compile_expr("count(units, 'item.carpet_area_m2 <= 60') >= 1")
    assert "units[*].carpet_area_m2" in c.paths


def test_any_all_three_valued():
    assert ev("any([derived.far > 1, site.edges['e2'].road_width_m > 0])").value is True
    assert ev("all([derived.far > 99, site.edges['e2'].road_width_m > 0])").value is False
    assert ev("all([derived.far > 1, site.edges['e2'].road_width_m > 0])").is_missing


def test_sum_and_min_over_lists():
    ctx = {**CTX, "derived": {**CTX["derived"], "areas": [1.5, 2.5, 3.0]}}
    assert ev("sum(derived.areas)", ctx=ctx).value == 7.0
    assert ev("min(derived.areas)", ctx=ctx).value == 1.5


# ---------------------------------------------------------------- static paths


def test_static_paths_are_full_chains_only():
    c = compile_expr("project.occupancy.subdivision == 'A-4' and derived.setback_m[item.id] > 3")
    assert c.paths == {"project.occupancy.subdivision", "derived.setback_m", "item.id"}


# ---------------------------------------------------------------- rejections


@pytest.mark.parametrize(
    "src",
    [
        "().__class__",
        "project.__class__",
        "project._private",
        "__import__('os')",
        "open('x')",
        "eval('1')",
        "lambda: 1",
        "[x for x in units]",
        "{x for x in units}",
        "{'a': 1}",
        "project.zone.upper()",
        "min(1, key=abs)",
        "max(*units)",
        "x + 1",  # unknown name
        "f'{project}'",
        "project := 1",
        "b'bytes'",
        "table(project.zone, 1)",  # table name must be a literal
        "count(units, project.zone)",  # predicate must be a literal
        "count(units, 'item.__class__')",  # predicate is checked too
        "len()",
        "1 +",
        "",
        "x" * 2001,
    ],
)
def test_rejects_unsafe_or_invalid(src):
    with pytest.raises(ExprError):
        compile_expr(src)


@pytest.mark.parametrize(
    "src",
    [
        "10 ** 100",  # exponent limit
        "1 / 0",
        "project.zone + 1",  # string arithmetic
        "project.nope",  # unknown field is a rule bug, not missing data
        "units['U9']",
        "units[99]",
        "item.width_m",  # item outside for_each
        "len(derived.far)",
    ],
)
def test_runtime_errors_are_expr_errors(src):
    with pytest.raises(ExprError):
        ev(src)


def test_too_many_nodes():
    with pytest.raises(ExprError, match="nodes"):
        compile_expr(" + ".join(["1"] * 300))
