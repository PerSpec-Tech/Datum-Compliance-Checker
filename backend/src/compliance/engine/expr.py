"""Safe evaluator for rule expressions.

Rule files hold small Python-syntax expressions such as ``item.width_m >= limit``. They are parsed
with ``ast`` and run by a tiny tree-walking interpreter over an allow-list of node types. Python's
``eval``/``exec`` are never used.

Two things make this more than a calculator:

* **Facts** — a ``{"value": …, "source": …}`` dict from the BuildingModel is unwrapped to its value
  automatically, and every fact read is recorded so a result can show what it relied on.
* **Missing values** — reading ``null`` produces a ``Missing`` sentinel that remembers the path
  it came from. Arithmetic and comparisons on ``Missing`` give ``Missing``; ``and``, ``or``,
  ``any`` and ``all`` use three-valued (Kleene) logic, so ``False and <missing>`` is still
  ``False``. A final ``Missing`` becomes a "cannot verify" result naming the inputs needed.
"""

from __future__ import annotations

import ast
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

# Names an expression may start from. `item` exists inside for_each; `limit`/`measured` are the
# rule's own named expressions.
ROOT_NAMES = frozenset(
    {
        "project", "site", "building", "levels", "spaces", "areas", "stairs", "doors", "units",
        "derived", "item", "limit", "measured",
    }
)  # fmt: skip
FUNCTIONS = frozenset(
    {"min", "max", "abs", "round", "len", "sum", "any", "all", "between", "table", "count"}
)
FACT_KEYS = frozenset({"value", "source", "note", "confidence"})

MAX_SOURCE_LEN = 2000
MAX_NODES = 400
MAX_POW_EXPONENT = 64

_BIN_OPS = {
    ast.Add: lambda a, b: a + b,
    ast.Sub: lambda a, b: a - b,
    ast.Mult: lambda a, b: a * b,
    ast.Div: lambda a, b: a / b,
    ast.FloorDiv: lambda a, b: a // b,
    ast.Mod: lambda a, b: a % b,
    ast.Pow: lambda a, b: a**b,
}
_CMP_OPS = {
    ast.Eq: lambda a, b: a == b,
    ast.NotEq: lambda a, b: a != b,
    ast.Lt: lambda a, b: a < b,
    ast.LtE: lambda a, b: a <= b,
    ast.Gt: lambda a, b: a > b,
    ast.GtE: lambda a, b: a >= b,
    ast.In: lambda a, b: a in b,
    ast.NotIn: lambda a, b: a not in b,
}
_ALLOWED_NODES = (
    ast.Expression, ast.Constant, ast.Name, ast.Load, ast.Attribute, ast.Subscript,
    ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare, ast.IfExp, ast.Call, ast.List, ast.Tuple,
    ast.UAdd, ast.USub, ast.Not, ast.And, ast.Or,
    *_BIN_OPS, *_CMP_OPS,
)  # fmt: skip


class ExprError(Exception):
    """The expression is invalid or can't be evaluated (a bug in the rule, not missing data)."""


@dataclass(frozen=True)
class Missing:
    """A value that couldn't be read. `paths` are the inputs that would make it known."""

    paths: frozenset[str]

    def __bool__(self) -> bool:  # pragma: no cover - guards against accidental truth tests
        raise ExprError("internal error: Missing used as a boolean")


@dataclass(frozen=True)
class FactRead:
    path: str
    value: Any
    source: str


@dataclass(frozen=True)
class EvalResult:
    value: Any  # None when missing
    missing: frozenset[str]  # empty when the value is known
    facts: tuple[FactRead, ...]  # facts read, in order, de-duplicated by path
    accessed: frozenset[str]  # every path read

    @property
    def is_missing(self) -> bool:
        return bool(self.missing)


@dataclass(frozen=True)
class Compiled:
    source: str
    tree: ast.Expression = field(repr=False)
    paths: frozenset[str]  # attribute chains read, e.g. 'project.zone', 'item.width_m'
    tables: frozenset[str]  # table names used by table()
    subs: Mapping[str, Compiled] = field(repr=False)  # count() predicates, by source

    def eval(
        self,
        ctx: Mapping[str, Any],
        *,
        tables: Mapping[str, Mapping[str, Any]] | None = None,
        labels: Mapping[str, str] | None = None,
    ) -> EvalResult:
        """Evaluate against `ctx` (root name → plain JSON-like data).

        `tables` maps table name → table document (schemas/table.schema.json).
        `labels` renames roots in reported paths, e.g. {"item": "doors[D1]"}.
        """
        run = _Run(self, ctx, tables or {}, labels or {})
        value = run.ev(self.tree.body)
        facts: dict[str, FactRead] = {}
        for f in run.facts:
            facts.setdefault(f.path, f)
        if isinstance(value, Missing):
            return EvalResult(None, value.paths, tuple(facts.values()), frozenset(run.accessed))
        return EvalResult(value, frozenset(), tuple(facts.values()), frozenset(run.accessed))


# --------------------------------------------------------------------------- compile


def compile_expr(source: str) -> Compiled:
    """Parse and check an expression. Raises ExprError if anything is outside the allow-list."""
    if not isinstance(source, str) or not source.strip():
        raise ExprError("expression must be a non-empty string")
    if len(source) > MAX_SOURCE_LEN:
        raise ExprError(f"expression longer than {MAX_SOURCE_LEN} characters")
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except SyntaxError as e:
        raise ExprError(f"syntax error: {e.msg}") from None
    nodes = list(ast.walk(tree))
    if len(nodes) > MAX_NODES:
        raise ExprError(f"expression has more than {MAX_NODES} nodes")
    checker = _Checker()
    checker.visit(tree)
    return Compiled(
        source=source,
        tree=tree,
        paths=frozenset(checker.paths),
        tables=frozenset(checker.tables),
        subs=checker.subs,
    )


def _chain(node: ast.AST) -> str | None:
    """'project.occupancy.group' for a pure Name/Attribute chain, else None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        return ".".join([node.id, *reversed(parts)])
    return None


class _Checker(ast.NodeVisitor):
    def __init__(self) -> None:
        self.paths: set[str] = set()
        self.tables: set[str] = set()
        self.subs: dict[str, Compiled] = {}

    def generic_visit(self, node: ast.AST) -> None:
        if not isinstance(node, _ALLOWED_NODES):
            raise ExprError(f"'{type(node).__name__}' is not allowed in rule expressions")
        super().generic_visit(node)

    def visit_Constant(self, node: ast.Constant) -> None:
        if not (node.value is None or isinstance(node.value, (bool, int, float, str))):
            raise ExprError(f"constant of type {type(node.value).__name__} is not allowed")

    def visit_Name(self, node: ast.Name) -> None:
        if node.id not in ROOT_NAMES:
            raise ExprError(f"unknown name '{node.id}'")
        self.paths.add(node.id)

    def visit_Attribute(self, node: ast.Attribute) -> None:
        if node.attr.startswith("_"):
            raise ExprError(f"attribute '{node.attr}' is not allowed (names starting with '_')")
        chain = _chain(node)
        if chain is not None:
            if chain.split(".", 1)[0] not in ROOT_NAMES:
                raise ExprError(f"unknown name '{chain.split('.', 1)[0]}'")
            self.paths.add(chain)  # don't descend: the prefixes aren't separate reads
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if not isinstance(node.func, ast.Name) or node.func.id not in FUNCTIONS:
            name = node.func.id if isinstance(node.func, ast.Name) else ast.unparse(node.func)
            raise ExprError(f"function '{name}' is not allowed")
        if node.keywords:
            raise ExprError("keyword arguments are not allowed")
        if any(isinstance(a, ast.Starred) for a in node.args):
            raise ExprError("*args are not allowed")
        fn, args = node.func.id, node.args
        arity = {"abs": (1, 1), "round": (1, 2), "len": (1, 1), "sum": (1, 1), "any": (1, 1),
                 "all": (1, 1), "between": (3, 3), "count": (2, 2), "table": (2, 3),
                 "min": (1, 99), "max": (1, 99)}[fn]  # fmt: skip
        if not arity[0] <= len(args) <= arity[1]:
            raise ExprError(f"{fn}() takes {arity[0]}–{arity[1]} arguments, got {len(args)}")
        if fn == "table":
            if not (isinstance(args[0], ast.Constant) and isinstance(args[0].value, str)):
                raise ExprError("table() needs the table name as a string literal first")
            self.tables.add(args[0].value)
            for a in args[1:]:
                self.visit(a)
            return
        if fn == "count":
            if not (isinstance(args[1], ast.Constant) and isinstance(args[1].value, str)):
                raise ExprError("count() needs the predicate as a string literal second")
            self.visit(args[0])
            sub = compile_expr(args[1].value)
            self.subs[args[1].value] = sub
            self.tables |= sub.tables
            prefix = (_chain(args[0]) or "<collection>") + "[*]"
            for p in sub.paths:
                if p == "item" or p.startswith("item."):
                    self.paths.add(prefix + p[len("item") :])
                else:
                    self.paths.add(p)
            return
        for a in args:
            self.visit(a)


# --------------------------------------------------------------------------- evaluate


def _missing_of(*values: Any) -> Missing | None:
    paths: set[str] = set()
    for v in values:
        if isinstance(v, Missing):
            paths |= v.paths
    return Missing(frozenset(paths)) if paths else None


def _is_fact(v: Any) -> bool:
    return isinstance(v, dict) and "value" in v and "source" in v and set(v) <= FACT_KEYS


def _num(v: Any, what: str) -> float | int:
    if isinstance(v, bool) or not isinstance(v, (int, float)):
        raise ExprError(f"{what} needs a number, got {type(v).__name__}")
    return v


class _Run:
    def __init__(self, compiled: Compiled, ctx, tables, labels) -> None:
        self.compiled = compiled
        self.ctx = ctx
        self.tables = tables
        self.labels = labels
        self.facts: list[FactRead] = []
        self.accessed: set[str] = set()

    # -- references (Name / Attribute / Subscript) keep track of their path

    def _settle(self, value: Any, path: str) -> tuple[Any, str]:
        self.accessed.add(path)
        if _is_fact(value):
            self.facts.append(FactRead(path, value["value"], value["source"]))
            value = value["value"]
        if value is None:
            return Missing(frozenset({path})), path
        return value, path

    def ref(self, node: ast.AST) -> tuple[Any, str | None]:
        if isinstance(node, ast.Name):
            if node.id not in self.ctx:
                raise ExprError(f"'{node.id}' is not available here")
            return self._settle(self.ctx[node.id], self.labels.get(node.id, node.id))
        if isinstance(node, ast.Attribute):
            base, path = self.ref(node.value)
            if isinstance(base, Missing):
                return base, None
            if not isinstance(base, dict):
                raise ExprError(f"can't read '.{node.attr}' of a {type(base).__name__} at {path}")
            if node.attr not in base:
                raise ExprError(f"no field '{node.attr}' at {path}")
            return self._settle(base[node.attr], f"{path}.{node.attr}")
        if isinstance(node, ast.Subscript):
            base, path = self.ref(node.value)
            key = self.ev(node.slice)
            if (m := _missing_of(base, key)) is not None:
                return m, None
            sub_path = f"{path}[{key}]"
            if isinstance(base, dict):
                if key not in base:
                    return Missing(frozenset({sub_path})), sub_path
                return self._settle(base[key], sub_path)
            if isinstance(base, list):
                if isinstance(key, str):  # spaces['S1'] → the element with that id
                    for el in base:
                        if isinstance(el, dict) and el.get("id") == key:
                            return self._settle(el, sub_path)
                    raise ExprError(f"no element with id '{key}' in {path}")
                is_index = isinstance(key, int) and not isinstance(key, bool)
                if is_index and -len(base) <= key < len(base):
                    return self._settle(base[key], sub_path)
                raise ExprError(f"index {key!r} out of range for {path}")
            raise ExprError(f"can't index a {type(base).__name__} at {path}")
        return self.ev(node), None

    # -- values

    def ev(self, node: ast.AST) -> Any:
        if isinstance(node, ast.Constant):
            return node.value
        if isinstance(node, (ast.Name, ast.Attribute, ast.Subscript)):
            return self.ref(node)[0]
        if isinstance(node, (ast.List, ast.Tuple)):
            items = [self.ev(e) for e in node.elts]
            m = _missing_of(*items)
            return items if m is None else m
        if isinstance(node, ast.BinOp):
            return self._binop(node)
        if isinstance(node, ast.UnaryOp):
            v = self.ev(node.operand)
            if isinstance(v, Missing):
                return v
            if isinstance(node.op, ast.Not):
                return not v
            v = _num(v, "unary minus/plus")
            return -v if isinstance(node.op, ast.USub) else +v
        if isinstance(node, ast.BoolOp):
            return self._boolop(node)
        if isinstance(node, ast.Compare):
            return self._compare(node)
        if isinstance(node, ast.IfExp):
            test = self.ev(node.test)
            if isinstance(test, Missing):
                return test
            return self.ev(node.body) if test else self.ev(node.orelse)
        if isinstance(node, ast.Call):
            return self._call(node)
        raise ExprError(f"'{type(node).__name__}' is not allowed")  # pragma: no cover

    def _binop(self, node: ast.BinOp) -> Any:
        left, right = self.ev(node.left), self.ev(node.right)
        if (m := _missing_of(left, right)) is not None:
            return m
        left, right = _num(left, "arithmetic"), _num(right, "arithmetic")
        if isinstance(node.op, ast.Pow) and abs(right) > MAX_POW_EXPONENT:
            raise ExprError(f"exponent larger than {MAX_POW_EXPONENT}")
        try:
            result = _BIN_OPS[type(node.op)](left, right)
        except ZeroDivisionError:
            raise ExprError(f"division by zero in '{ast.unparse(node)}'") from None
        if isinstance(result, float) and not math.isfinite(result):
            raise ExprError(f"non-finite result in '{ast.unparse(node)}'")
        return result

    def _boolop(self, node: ast.BoolOp) -> Any:
        is_and = isinstance(node.op, ast.And)
        missing: set[str] = set()
        for value_node in node.values:
            v = self.ev(value_node)
            if isinstance(v, Missing):
                missing |= v.paths
            elif is_and and not v:
                return False  # known False decides an 'and' regardless of missing parts
            elif not is_and and v:
                return True  # known True decides an 'or'
        return Missing(frozenset(missing)) if missing else is_and

    def _compare(self, node: ast.Compare) -> Any:
        left = self.ev(node.left)
        rights = [self.ev(c) for c in node.comparators]
        if (m := _missing_of(left, *rights)) is not None:
            return m
        for op, right in zip(node.ops, rights, strict=True):
            try:
                ok = _CMP_OPS[type(op)](left, right)
            except TypeError:
                raise ExprError(
                    f"can't compare {type(left).__name__} and {type(right).__name__} "
                    f"in '{ast.unparse(node)}'"
                ) from None
            if not ok:
                return False
            left = right
        return True

    def _iter_values(self, v: Any, fn: str) -> list[Any] | Missing:
        if isinstance(v, Missing):
            return v
        if not isinstance(v, (list, tuple)):
            raise ExprError(f"{fn}() needs a list")
        vals = [x["value"] if _is_fact(x) else x for x in v]
        vals = [
            Missing(frozenset({f"{fn}()[{i}]"})) if x is None else x for i, x in enumerate(vals)
        ]
        m = _missing_of(*vals)
        return vals if m is None else m

    def _call(self, node: ast.Call) -> Any:
        fn, args = node.func.id, node.args  # type: ignore[union-attr]
        if fn == "count":
            return self._count(node)
        if fn == "table":
            keys = [self.ev(a) for a in args[1:]]
            if (m := _missing_of(*keys)) is not None:
                return m
            return self._table(args[0].value, keys)  # type: ignore[union-attr]
        if fn in ("any", "all"):
            # A literal list is evaluated element by element so a known True/False still decides.
            if isinstance(args[0], (ast.List, ast.Tuple)):
                items = [self.ev(e) for e in args[0].elts]
            else:
                items = self.ev(args[0])
            if isinstance(items, Missing):
                return items
            if not isinstance(items, (list, tuple)):
                raise ExprError(f"{fn}() needs a list")
            missing: set[str] = set()
            for x in items:
                x = x["value"] if _is_fact(x) else x
                if x is None or isinstance(x, Missing):
                    missing |= x.paths if isinstance(x, Missing) else {f"{fn}()[item]"}
                elif fn == "any" and x:
                    return True
                elif fn == "all" and not x:
                    return False
            return Missing(frozenset(missing)) if missing else fn == "all"
        vals = [self.ev(a) for a in args]
        if (m := _missing_of(*vals)) is not None:
            return m
        if fn in ("min", "max", "sum") and len(vals) == 1:
            items = self._iter_values(vals[0], fn)
            if isinstance(items, Missing):
                return items
            nums = [_num(x, f"{fn}()") for x in items]
            if fn == "sum":
                return sum(nums)
            if not nums:
                raise ExprError(f"{fn}() of an empty list")
            return min(nums) if fn == "min" else max(nums)
        if fn in ("min", "max"):
            nums = [_num(x, f"{fn}()") for x in vals]
            return min(nums) if fn == "min" else max(nums)
        if fn == "abs":
            return abs(_num(vals[0], "abs()"))
        if fn == "round":
            digits = 0 if len(vals) == 1 else int(_num(vals[1], "round() digits"))
            return round(_num(vals[0], "round()"), digits)
        if fn == "len":
            if not isinstance(vals[0], (list, tuple, dict, str)):
                raise ExprError("len() needs a list, dict or string")
            return len(vals[0])
        if fn == "between":
            x, lo, hi = (_num(v, "between()") for v in vals)
            return lo <= x <= hi
        raise ExprError(f"function '{fn}' is not allowed")  # pragma: no cover

    def _count(self, node: ast.Call) -> Any:
        coll, path = self.ref(node.args[0])
        if isinstance(coll, Missing):
            return coll
        if not isinstance(coll, list):
            raise ExprError("count() needs a list as its first argument")
        sub = self.compiled.subs[node.args[1].value]  # type: ignore[union-attr]
        n, missing = 0, set()
        for i, el in enumerate(coll):
            label = f"{path or '<collection>'}[{el.get('id', i) if isinstance(el, dict) else i}]"
            run = _Run(sub, {**self.ctx, "item": el}, self.tables, {**self.labels, "item": label})
            v = run.ev(sub.tree.body)
            self.facts += run.facts
            self.accessed |= run.accessed
            if isinstance(v, Missing):
                missing |= v.paths
            elif v:
                n += 1
        return Missing(frozenset(missing)) if missing else n

    def _table(self, name: str, keys: list[Any]) -> Any:
        doc = self.tables.get(name)
        if doc is None:
            raise ExprError(f"unknown table '{name}'")
        label = f"table:{name}[{', '.join(map(str, keys))}]"
        kind = doc["kind"]
        if kind == "map":
            if len(keys) != 1:
                raise ExprError(f"table '{name}' (map) takes 1 key")
            value = doc["map"].get(_key(keys[0]), _ABSENT)
        elif kind == "bands":
            if len(keys) != 1:
                raise ExprError(f"table '{name}' (bands) takes 1 key")
            value = _band(doc["bands"], _num(keys[0], f"table '{name}' key"))
        elif kind == "map_of_bands":
            if len(keys) != 2:
                raise ExprError(f"table '{name}' (map_of_bands) takes 2 keys")
            bands = doc["map_of_bands"].get(_key(keys[0]))
            value = _ABSENT if bands is None else _band(bands, _num(keys[1], f"table '{name}' key"))
        else:
            raise ExprError(f"table '{name}' has unknown kind '{kind}'")
        self.accessed.add(label)
        if value is _ABSENT or value is None:  # no entry, or the table gives no value for it
            return Missing(frozenset({label}))
        return value


_ABSENT = object()


def _key(k: Any) -> str:
    if isinstance(k, bool):
        return "true" if k else "false"
    if isinstance(k, float) and k.is_integer():
        return str(int(k))
    return str(k)


def _band(bands: list[Mapping[str, Any]], x: float) -> Any:
    for b in bands:
        if b["min"] <= x and (b["max"] is None or x < b["max"]):
            return b["value"]
    return _ABSENT
