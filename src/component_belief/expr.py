"""A deliberately small expression language for acceptance rules and condition
predicates.

`belief.yaml` is human-authored and git-reviewed, but it is still parsed by a
server that an agent talks to. `eval()` here would make the declaration file a
code-execution surface, so this is an AST walk over a fixed whitelist instead:
comparisons, boolean logic, arithmetic, and membership. No calls, no
attributes, no subscripts, no names beyond the supplied variables.
"""

from __future__ import annotations

import ast
from typing import Any, Mapping

_ALLOWED_NODES = (
    ast.Expression,
    ast.BoolOp, ast.And, ast.Or,
    ast.UnaryOp, ast.Not, ast.USub, ast.UAdd,
    ast.BinOp, ast.Add, ast.Sub, ast.Mult, ast.Div, ast.Mod, ast.Pow,
    ast.Compare,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE, ast.In, ast.NotIn,
    ast.Name, ast.Load, ast.Constant,
    ast.List, ast.Tuple, ast.Set,
)

_CONSTANTS: dict[str, Any] = {"true": True, "false": False, "null": None, "None": None}


class ExprError(ValueError):
    """Raised for a malformed rule, or one referencing an undefined name."""


def _parse(source: str) -> ast.Expression:
    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as exc:
        raise ExprError(f"cannot parse {source!r}: {exc.msg}") from exc
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExprError(
                f"{type(node).__name__} is not permitted in a rule: {source!r}"
            )
    return tree


def referenced_names(source: str) -> set[str]:
    """Free variables in a rule — used to check a contract against a test's
    declared metrics (2.6) before any evidence is accepted."""
    tree = _parse(source)
    return {
        node.id
        for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id not in _CONSTANTS
    }


def _eval(node: ast.AST, env: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Expression):
        return _eval(node.body, env)
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, ast.Name):
        if node.id in _CONSTANTS:
            return _CONSTANTS[node.id]
        if node.id not in env:
            raise ExprError(f"undefined name {node.id!r}")
        return env[node.id]
    if isinstance(node, ast.BoolOp):
        values = [_eval(v, env) for v in node.values]
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.UnaryOp):
        operand = _eval(node.operand, env)
        if isinstance(node.op, ast.Not):
            return not operand
        return -operand if isinstance(node.op, ast.USub) else +operand
    if isinstance(node, ast.BinOp):
        left, right = _eval(node.left, env), _eval(node.right, env)
        op = node.op
        if isinstance(op, ast.Add):
            return left + right
        if isinstance(op, ast.Sub):
            return left - right
        if isinstance(op, ast.Mult):
            return left * right
        if isinstance(op, ast.Div):
            return left / right
        if isinstance(op, ast.Mod):
            return left % right
        if isinstance(op, ast.Pow):
            return left ** right
    if isinstance(node, ast.Compare):
        left = _eval(node.left, env)
        for op, comparator in zip(node.ops, node.comparators):
            right = _eval(comparator, env)
            if isinstance(op, ast.Eq):
                ok = left == right
            elif isinstance(op, ast.NotEq):
                ok = left != right
            elif isinstance(op, ast.Lt):
                ok = left < right
            elif isinstance(op, ast.LtE):
                ok = left <= right
            elif isinstance(op, ast.Gt):
                ok = left > right
            elif isinstance(op, ast.GtE):
                ok = left >= right
            elif isinstance(op, ast.In):
                ok = left in right
            else:
                ok = left not in right
            if not ok:
                return False
            left = right
        return True
    if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
        return [_eval(e, env) for e in node.elts]
    raise ExprError(f"unsupported node {type(node).__name__}")


def evaluate(source: str, env: Mapping[str, Any]) -> Any:
    """Evaluate a rule against a variable environment."""
    return _eval(_parse(source), env)


def evaluate_bool(source: str, env: Mapping[str, Any]) -> bool:
    return bool(evaluate(source, env))


def looks_like_implementation_detail(source: str) -> str | None:
    """Heuristic for rule 2.3: a capability claim must not be phrased in terms
    of implementation internals. Returns the offending token, or None.

    Deliberately conservative — it catches file paths and private symbols, the
    two forms that show up in practice. Subtler leakage is the auditor's job.
    """
    for name in referenced_names(source):
        if name.startswith("_"):
            return name
    for token in ("/", "\\", ".py", "::"):
        if token in source:
            return token
    return None
