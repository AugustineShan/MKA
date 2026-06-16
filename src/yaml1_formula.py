"""Restricted formula/DAG evaluator for YAML1.

The evaluator intentionally stays small and deterministic. It evaluates
formula nodes into yearly series before yaml1_cleaner resolves overlays onto
YAML2, so calc.py never needs to understand formula syntax.
"""

from __future__ import annotations

import ast
import math
import operator
import re
from dataclasses import dataclass, field
from typing import Any

from src.yaml2_schema import plain_value


NODE_ID_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
ALLOWED_FUNCTIONS = {"lag", "min", "max", "abs", "clip", "if_else"}


class FormulaError(RuntimeError):
    """Raised when a formula graph cannot be evaluated safely."""


@dataclass
class FormulaNode:
    node_id: str
    kind: str
    unit: str
    src: str | None = None
    values: list[float] | None = None
    expr: str | None = None
    inputs: list[str] = field(default_factory=list)
    seeds: dict[int, float] = field(default_factory=dict)
    history: dict[int, float] = field(default_factory=dict)
    tolerance: float | None = None


@dataclass
class FormulaResult:
    horizon: list[int]
    nodes: dict[str, FormulaNode]
    values_by_node: dict[str, dict[int, float]]
    dependencies: dict[str, dict[int, list[str]]]
    backtests: dict[str, dict[str, Any]]
    warnings: list[dict[str, Any]]
    targets: dict[str, str] = field(default_factory=dict)

    def values(self, node_id: str) -> list[float]:
        if node_id not in self.values_by_node:
            raise FormulaError(f"Unknown formula node: {node_id}")
        return [self.values_by_node[node_id][year] for year in self.horizon]

    def report(self) -> dict[str, Any]:
        nodes_report: dict[str, Any] = {}
        for node_id, node in self.nodes.items():
            nodes_report[node_id] = {
                "kind": node.kind,
                "unit": node.unit,
                "expr": node.expr,
                "inputs": node.inputs,
                "values": {
                    str(year): self.values_by_node.get(node_id, {}).get(year)
                    for year in self.horizon
                    if year in self.values_by_node.get(node_id, {})
                },
                "dependencies": {
                    str(year): deps
                    for year, deps in self.dependencies.get(node_id, {}).items()
                },
                "backtest": self.backtests.get(node_id, {"status": "skipped", "reason": "not_applicable"}),
            }
            if node.src:
                nodes_report[node_id]["src"] = node.src
            if node.history:
                nodes_report[node_id]["history_years"] = sorted(node.history)
            if node.seeds:
                nodes_report[node_id]["seed_years"] = sorted(node.seeds)
        status = "ok"
        return {
            "status": status,
            "nodes": nodes_report,
            "targets": self.targets,
            "warnings": self.warnings,
        }


def evaluate_formula_graph(yaml1: dict[str, Any], horizon: list[int]) -> FormulaResult:
    formulas = yaml1.get("formulas")
    if formulas is None:
        return FormulaResult(horizon=horizon, nodes={}, values_by_node={}, dependencies={}, backtests={}, warnings=[])
    if not isinstance(formulas, dict):
        raise FormulaError("formulas must be a mapping")
    nodes_any = formulas.get("nodes", {})
    if not isinstance(nodes_any, dict):
        raise FormulaError("formulas.nodes must be a mapping")

    nodes = {node_id: _parse_node(node_id, node_any, horizon) for node_id, node_any in nodes_any.items()}
    for node in nodes.values():
        if node.kind == "formula":
            _validate_formula_node(node, nodes)

    evaluator = _FormulaEvaluator(nodes, horizon)
    values_by_node = evaluator.evaluate_all()
    backtests, warnings = evaluator.backtest_all()
    return FormulaResult(
        horizon=horizon,
        nodes=nodes,
        values_by_node=values_by_node,
        dependencies=evaluator.dependencies,
        backtests=backtests,
        warnings=warnings,
    )


def _parse_node(node_id: str, node_any: Any, horizon: list[int]) -> FormulaNode:
    if not NODE_ID_RE.match(str(node_id)):
        raise FormulaError(f"Invalid formula node id: {node_id}")
    if not isinstance(node_any, dict):
        raise FormulaError(f"formulas.nodes.{node_id} must be a mapping")
    kind = str(node_any.get("kind", ""))
    if kind not in {"input", "formula"}:
        raise FormulaError(f"Unsupported formula node kind at {node_id}: {kind}")
    unit = node_any.get("unit")
    if not isinstance(unit, str) or not unit:
        raise FormulaError(f"formulas.nodes.{node_id}.unit is required")

    values: list[float] | None = None
    expr: str | None = None
    inputs: list[str] = []
    if kind == "input":
        values = _year_values(node_any.get("values"), horizon, f"formulas.nodes.{node_id}.values")
    else:
        expr_any = node_any.get("expr")
        if not isinstance(expr_any, str) or not expr_any.strip():
            raise FormulaError(f"formulas.nodes.{node_id}.expr is required")
        expr = expr_any
        inputs_any = node_any.get("inputs")
        if not isinstance(inputs_any, list) or not all(isinstance(item, str) for item in inputs_any):
            raise FormulaError(f"formulas.nodes.{node_id}.inputs must be a list of node ids")
        inputs = list(inputs_any)

    return FormulaNode(
        node_id=str(node_id),
        kind=kind,
        unit=unit,
        src=node_any.get("src") if isinstance(node_any.get("src"), str) else None,
        values=values,
        expr=expr,
        inputs=inputs,
        seeds=_number_mapping(node_any.get("seeds", {}), f"formulas.nodes.{node_id}.seeds"),
        history=_number_mapping(node_any.get("history", {}), f"formulas.nodes.{node_id}.history"),
        tolerance=_optional_float(node_any.get("tolerance")),
    )


def _year_values(values_any: Any, horizon: list[int], path: str) -> list[float]:
    values_any = plain_value(values_any)
    if not isinstance(values_any, list):
        raise FormulaError(f"{path} must be a list")
    if len(values_any) != len(horizon):
        raise FormulaError(f"{path} length {len(values_any)} != horizon length {len(horizon)}")
    return [_to_float(value, path) for value in values_any]


def _number_mapping(value_any: Any, path: str) -> dict[int, float]:
    value_any = plain_value(value_any)
    if value_any in (None, ""):
        return {}
    if not isinstance(value_any, dict):
        raise FormulaError(f"{path} must be a mapping")
    out: dict[int, float] = {}
    for key, value in value_any.items():
        try:
            year = int(key)
        except (TypeError, ValueError) as exc:
            raise FormulaError(f"{path} key must be a year: {key}") from exc
        out[year] = _to_float(value, f"{path}.{key}")
    return out


def _optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(plain_value(value))


def _to_float(value: Any, path: str) -> float:
    value = plain_value(value)
    try:
        out = float(value)
    except (TypeError, ValueError) as exc:
        raise FormulaError(f"{path} must be numeric") from exc
    if not math.isfinite(out):
        raise FormulaError(f"{path} must be finite")
    return out


def _validate_formula_node(node: FormulaNode, nodes: dict[str, FormulaNode]) -> None:
    assert node.expr is not None
    try:
        tree = ast.parse(node.expr, mode="eval")
    except SyntaxError as exc:
        raise FormulaError(f"Invalid formula expression at {node.node_id}: {node.expr}") from exc
    refs = _ExpressionValidator(node.node_id).validate(tree)
    input_set = set(node.inputs)
    for ref in refs:
        if ref not in nodes:
            raise FormulaError(f"Formula node {node.node_id} references unknown node: {ref}")
    missing = sorted(refs - input_set)
    unused = sorted(input_set - refs)
    if missing:
        raise FormulaError(f"Formula node {node.node_id} references undeclared inputs: {missing}")
    if unused:
        raise FormulaError(f"Formula node {node.node_id} declares unused inputs: {unused}")


class _ExpressionValidator:
    def __init__(self, node_id: str) -> None:
        self.node_id = node_id
        self.refs: set[str] = set()

    def validate(self, tree: ast.AST) -> set[str]:
        self._visit(tree)
        return set(self.refs)

    def _visit(self, node: ast.AST) -> None:
        if isinstance(node, ast.Expression):
            self._visit(node.body)
            return
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float, bool)):
                raise FormulaError(f"Unsupported constant in formula node {self.node_id}")
            return
        if isinstance(node, ast.Name):
            if node.id in ALLOWED_FUNCTIONS:
                raise FormulaError(f"Function name used as value in formula node {self.node_id}: {node.id}")
            self.refs.add(node.id)
            return
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.UAdd, ast.USub, ast.Not)):
            self._visit(node.operand)
            return
        if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)):
            self._visit(node.left)
            self._visit(node.right)
            return
        if isinstance(node, ast.Compare):
            self._visit(node.left)
            for op in node.ops:
                if not isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.Eq, ast.NotEq)):
                    raise FormulaError(f"Unsupported comparison in formula node {self.node_id}")
            for comparator in node.comparators:
                self._visit(comparator)
            return
        if isinstance(node, ast.BoolOp) and isinstance(node.op, (ast.And, ast.Or)):
            for value in node.values:
                self._visit(value)
            return
        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name) or node.func.id not in ALLOWED_FUNCTIONS:
                raise FormulaError(f"Unsupported function in formula node {self.node_id}")
            if node.keywords:
                raise FormulaError(f"Keyword arguments are not allowed in formula node {self.node_id}")
            if node.func.id == "lag":
                if len(node.args) != 2 or not isinstance(node.args[0], ast.Name):
                    raise FormulaError(f"lag(node, n) requires a node id and integer lag in {self.node_id}")
                lag_arg = node.args[1]
                if not isinstance(lag_arg, ast.Constant) or not isinstance(lag_arg.value, int) or lag_arg.value <= 0:
                    raise FormulaError(f"lag(node, n) requires a positive integer lag in {self.node_id}")
                self.refs.add(node.args[0].id)
                return
            for arg in node.args:
                self._visit(arg)
            return
        raise FormulaError(f"Unsupported expression syntax in formula node {self.node_id}: {type(node).__name__}")


class _FormulaEvaluator:
    def __init__(self, nodes: dict[str, FormulaNode], horizon: list[int]) -> None:
        self.nodes = nodes
        self.horizon = horizon
        self.horizon_set = set(horizon)
        self.memo: dict[tuple[str, int], float] = {}
        self.visiting: list[tuple[str, int]] = []
        self.dependencies: dict[str, dict[int, list[str]]] = {}
        self._current_deps: list[str] | None = None

    def evaluate_all(self) -> dict[str, dict[int, float]]:
        values: dict[str, dict[int, float]] = {}
        for node_id in self.nodes:
            values[node_id] = {year: self.evaluate_node(node_id, year) for year in self.horizon}
        return values

    def evaluate_node(self, node_id: str, year: int) -> float:
        key = (node_id, year)
        if key in self.memo:
            return self.memo[key]
        node = self._require_node(node_id)
        if year not in self.horizon_set:
            return self._historical_value(node, year)
        if key in self.visiting:
            cycle = " -> ".join(f"{name}[{yr}]" for name, yr in [*self.visiting, key])
            raise FormulaError(f"Formula DAG cycle detected: {cycle}")
        self.visiting.append(key)
        try:
            if node.kind == "input":
                assert node.values is not None
                value = node.values[self.horizon.index(year)]
            else:
                assert node.expr is not None
                deps: list[str] = []
                previous_deps = self._current_deps
                self._current_deps = deps
                try:
                    value = self._eval_expr(node.expr, year)
                finally:
                    self._current_deps = previous_deps
                self.dependencies.setdefault(node_id, {})[year] = deps
            self.memo[key] = value
            return value
        finally:
            self.visiting.pop()

    def backtest_all(self) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
        backtests: dict[str, dict[str, Any]] = {}
        warnings: list[dict[str, Any]] = []
        for node_id, node in self.nodes.items():
            if node.kind != "formula":
                backtests[node_id] = {"status": "skipped", "reason": "input_node"}
                continue
            if not node.history:
                backtests[node_id] = {"status": "skipped", "reason": "missing_history"}
                warnings.append(
                    {
                        "stage": "formula",
                        "path": f"formulas.nodes.{node_id}",
                        "message": "formula node has no history; backtest skipped",
                    }
                )
                continue
            checked: list[int] = []
            skipped: list[int] = []
            errors: list[dict[str, Any]] = []
            tolerance = node.tolerance if node.tolerance is not None else _default_tolerance(node.unit)
            for year, expected in sorted(node.history.items()):
                try:
                    actual = self._eval_expr_history(node, year)
                except FormulaError:
                    skipped.append(year)
                    continue
                residual = actual - expected
                checked.append(year)
                if abs(residual) > tolerance:
                    errors.append(
                        {
                            "year": year,
                            "expected": expected,
                            "actual": actual,
                            "residual": residual,
                            "tolerance": tolerance,
                        }
                    )
            if errors:
                first = errors[0]
                raise FormulaError(
                    f"Formula node {node_id} backtest failed in {first['year']}: "
                    f"expected {first['expected']}, actual {first['actual']}, residual {first['residual']}"
                )
            if checked:
                max_abs_error = max(abs(self._eval_expr_history(node, year) - node.history[year]) for year in checked)
                backtests[node_id] = {
                    "status": "ok",
                    "checked_years": checked,
                    "skipped_years": skipped,
                    "max_abs_error": max_abs_error,
                    "tolerance": tolerance,
                }
            else:
                backtests[node_id] = {"status": "skipped", "reason": "missing_input_history", "skipped_years": skipped}
                warnings.append(
                    {
                        "stage": "formula",
                        "path": f"formulas.nodes.{node_id}",
                        "message": "formula node history exists but input history is incomplete; backtest skipped",
                    }
                )
        return backtests, warnings

    def _eval_expr(self, expr: str, year: int) -> float:
        tree = ast.parse(expr, mode="eval")
        value = self._eval_ast(tree.body, year)
        return float(value)

    def _eval_ast(self, node: ast.AST, year: int) -> float | bool:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return node.value
            if isinstance(node.value, (int, float)):
                return float(node.value)
            raise FormulaError("Unsupported formula constant")
        if isinstance(node, ast.Name):
            self._add_dependency(node.id, year)
            return self.evaluate_node(node.id, year)
        if isinstance(node, ast.UnaryOp):
            value = self._eval_ast(node.operand, year)
            if isinstance(node.op, ast.UAdd):
                return +float(value)
            if isinstance(node.op, ast.USub):
                return -float(value)
            if isinstance(node.op, ast.Not):
                return not bool(value)
        if isinstance(node, ast.BinOp):
            left = float(self._eval_ast(node.left, year))
            right = float(self._eval_ast(node.right, year))
            ops = {
                ast.Add: operator.add,
                ast.Sub: operator.sub,
                ast.Mult: operator.mul,
                ast.Div: operator.truediv,
            }
            for op_type, func in ops.items():
                if isinstance(node.op, op_type):
                    return float(func(left, right))
        if isinstance(node, ast.Compare):
            left = self._eval_ast(node.left, year)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_ast(comparator, year)
                if not _compare(left, right, op):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            values = [bool(self._eval_ast(value, year)) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
        if isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name)
            return self._eval_call(node.func.id, node.args, year)
        raise FormulaError(f"Unsupported formula expression at runtime: {type(node).__name__}")

    def _eval_call(self, func_name: str, args: list[ast.AST], year: int) -> float:
        if func_name == "lag":
            assert isinstance(args[0], ast.Name)
            lag_year = year - int(args[1].value)  # validator ensures constant int
            self._add_dependency(args[0].id, lag_year)
            return self.evaluate_node(args[0].id, lag_year)
        if func_name == "if_else":
            if len(args) != 3:
                raise FormulaError("if_else(condition, a, b) requires exactly three arguments")
            condition = bool(self._eval_ast(args[0], year))
            return float(self._eval_ast(args[1] if condition else args[2], year))
        values = [self._eval_ast(arg, year) for arg in args]
        if func_name == "min":
            return float(min(float(value) for value in values))
        if func_name == "max":
            return float(max(float(value) for value in values))
        if func_name == "abs":
            if len(values) != 1:
                raise FormulaError("abs() requires exactly one argument")
            return abs(float(values[0]))
        if func_name == "clip":
            if len(values) != 3:
                raise FormulaError("clip(x, low, high) requires exactly three arguments")
            x, low, high = [float(value) for value in values]
            return min(max(x, low), high)
        raise FormulaError(f"Unsupported formula function: {func_name}")

    def _eval_expr_history(self, node: FormulaNode, year: int) -> float:
        assert node.expr is not None
        tree = ast.parse(node.expr, mode="eval")
        return float(self._eval_ast_history(tree.body, year))

    def _eval_ast_history(self, node: ast.AST, year: int) -> float | bool:
        if isinstance(node, ast.Name):
            return self._historical_value(self._require_node(node.id), year)
        if isinstance(node, ast.Call):
            assert isinstance(node.func, ast.Name)
            if node.func.id == "lag":
                assert isinstance(node.args[0], ast.Name)
                lag_year = year - int(node.args[1].value)
                return self._historical_value(self._require_node(node.args[0].id), lag_year)
            if node.func.id == "if_else":
                condition = bool(self._eval_ast_history(node.args[0], year))
                return float(self._eval_ast_history(node.args[1] if condition else node.args[2], year))
            values = [self._eval_ast_history(arg, year) for arg in node.args]
            if node.func.id == "min":
                return float(min(float(value) for value in values))
            if node.func.id == "max":
                return float(max(float(value) for value in values))
            if node.func.id == "abs":
                if len(values) != 1:
                    raise FormulaError("abs() requires exactly one argument")
                return abs(float(values[0]))
            if node.func.id == "clip":
                if len(values) != 3:
                    raise FormulaError("clip(x, low, high) requires exactly three arguments")
                x, low, high = [float(value) for value in values]
                return min(max(x, low), high)
        if isinstance(node, ast.BinOp):
            left = float(self._eval_ast_history(node.left, year))
            right = float(self._eval_ast_history(node.right, year))
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                return left / right
        if isinstance(node, ast.UnaryOp):
            value = self._eval_ast_history(node.operand, year)
            if isinstance(node.op, ast.UAdd):
                return +float(value)
            if isinstance(node.op, ast.USub):
                return -float(value)
            if isinstance(node.op, ast.Not):
                return not bool(value)
        if isinstance(node, ast.Compare):
            left = self._eval_ast_history(node.left, year)
            for op, comparator in zip(node.ops, node.comparators):
                right = self._eval_ast_history(comparator, year)
                if not _compare(left, right, op):
                    return False
                left = right
            return True
        if isinstance(node, ast.BoolOp):
            values = [bool(self._eval_ast_history(value, year)) for value in node.values]
            if isinstance(node.op, ast.And):
                return all(values)
            if isinstance(node.op, ast.Or):
                return any(values)
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool):
                return node.value
            if isinstance(node.value, (int, float)):
                return float(node.value)
        raise FormulaError(f"Unsupported history formula expression: {type(node).__name__}")

    def _historical_value(self, node: FormulaNode, year: int) -> float:
        if year in node.seeds:
            return node.seeds[year]
        if year in node.history:
            return node.history[year]
        raise FormulaError(f"Formula node {node.node_id} missing seed/history for {year}")

    def _require_node(self, node_id: str) -> FormulaNode:
        if node_id not in self.nodes:
            raise FormulaError(f"Unknown formula node: {node_id}")
        return self.nodes[node_id]

    def _add_dependency(self, node_id: str, year: int) -> None:
        if self._current_deps is not None:
            self._current_deps.append(f"{node_id}[{year}]")


def _compare(left: Any, right: Any, op: ast.cmpop) -> bool:
    if isinstance(op, ast.Lt):
        return left < right
    if isinstance(op, ast.LtE):
        return left <= right
    if isinstance(op, ast.Gt):
        return left > right
    if isinstance(op, ast.GtE):
        return left >= right
    if isinstance(op, ast.Eq):
        return left == right
    if isinstance(op, ast.NotEq):
        return left != right
    raise FormulaError(f"Unsupported comparison operator: {type(op).__name__}")


def _default_tolerance(unit: str) -> float:
    unit_lower = unit.lower()
    if "million_cny" in unit_lower:
        return 1.0
    if "rate" in unit_lower or "ratio" in unit_lower or "pct" in unit_lower:
        return 0.001
    return 1e-6
