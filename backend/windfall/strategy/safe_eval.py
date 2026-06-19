"""Safe evaluator for strategy filter / rank expressions.

Replaces the previous ``eval(expr, {"__builtins__": {}}, ns)`` which was NOT a sandbox — a payload
like ``close.__class__.__init__.__globals__['__builtins__']['__import__']('os')`` escaped it and ran
arbitrary code. This evaluator walks a parsed AST and permits ONLY:

  - Names bound in the provided namespace (the pre-built feature panels / scalars)
  - Numeric / boolean constants
  - Arithmetic:  + - * / % **   (binary)  and unary  + -
  - Comparisons: > < >= <= == !=  (including chained, e.g. ``50 < rsi14 < 80``)
  - Boolean combination via & | ^ ~ (vectorized over pandas frames)
  - Parenthesisation

Attribute access, calls, subscripts, comprehensions, lambdas, names outside the namespace, and any
other node type are rejected with SafeEvalError. There is no path to builtins, imports, or dunders.
"""
from __future__ import annotations

import ast
import operator
from typing import Any

_BIN = {
    ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
    ast.Div: operator.truediv, ast.Mod: operator.mod, ast.Pow: operator.pow,
    ast.BitAnd: operator.and_, ast.BitOr: operator.or_, ast.BitXor: operator.xor,
}
_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg, ast.Invert: operator.invert}
_CMP = {
    ast.Gt: operator.gt, ast.Lt: operator.lt, ast.GtE: operator.ge, ast.LtE: operator.le,
    ast.Eq: operator.eq, ast.NotEq: operator.ne,
}


class SafeEvalError(ValueError):
    """Raised when an expression contains a disallowed construct or unknown name."""


def safe_eval(expr: str, namespace: dict[str, Any]) -> Any:
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError as exc:  # noqa: TRY003
        raise SafeEvalError(f"syntax error in '{expr}': {exc.msg}") from exc
    return _eval(tree.body, namespace, expr)


def _eval(node: ast.AST, ns: dict[str, Any], expr: str) -> Any:
    if isinstance(node, ast.BinOp) and type(node.op) in _BIN:
        return _BIN[type(node.op)](_eval(node.left, ns, expr), _eval(node.right, ns, expr))

    if isinstance(node, ast.UnaryOp) and type(node.op) in _UNARY:
        return _UNARY[type(node.op)](_eval(node.operand, ns, expr))

    if isinstance(node, ast.BoolOp):
        # `and`/`or` don't vectorize over frames; require & / | instead.
        raise SafeEvalError("use & / | (not 'and'/'or') to combine conditions")

    if isinstance(node, ast.Compare):
        left = _eval(node.left, ns, expr)
        result = None
        for op, comparator in zip(node.ops, node.comparators):
            if type(op) not in _CMP:
                raise SafeEvalError(f"comparison operator {type(op).__name__} not allowed")
            right = _eval(comparator, ns, expr)
            piece = _CMP[type(op)](left, right)
            result = piece if result is None else (result & piece)
            left = right
        return result

    if isinstance(node, ast.Name):
        if node.id not in ns:
            raise SafeEvalError(f"unknown name '{node.id}'")
        return ns[node.id]

    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float, bool)):
            return node.value
        raise SafeEvalError("only numeric/boolean literals are allowed")

    raise SafeEvalError(f"disallowed expression element: {type(node).__name__}")


def feature_names(expr: str) -> list[str]:
    """Return the Name identifiers referenced by an expression (for feature pre-building)."""
    try:
        tree = ast.parse(expr, mode="eval")
    except SyntaxError:
        return []
    return sorted({n.id for n in ast.walk(tree) if isinstance(n, ast.Name)})
