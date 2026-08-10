"""The escape hatch, and why it is barely one."""

from __future__ import annotations

import ast
import math
from typing import Any, Callable, Mapping

#: The only nodes that may appear. Anything else is a rejection.
_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.BinOp,
    ast.UnaryOp,
    ast.Call,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.Pow,
    ast.USub,
    ast.UAdd,
)

#: The only callables.
_FUNCTIONS: dict[str, Callable[..., float]] = {
    "min": min,
    "max": max,
    "round": round,
    "abs": abs,
    "floor": math.floor,
    "ceil": math.ceil,
}

#: `2 ** 10000` is a valid arithmetic expression and a denial of service.
MAX_EXPONENT = 64

#: Results beyond this are not a savings lesson. Same ceiling the registry uses.
MAX_MAGNITUDE = 1e11

#: How long an expression may be.
MAX_LENGTH = 200


class ExpressionError(ValueError):
    """The expression is not acceptable. Carries a human-readable reason."""


def parse(source: str, allowed_names: set[str]) -> ast.Expression:
    """Parse and validate, or raise `ExpressionError`."""
    if not source or not source.strip():
        raise ExpressionError("the expression is empty")
    if len(source) > MAX_LENGTH:
        raise ExpressionError(f"the expression is longer than {MAX_LENGTH} characters")

    try:
        tree = ast.parse(source, mode="eval")
    except SyntaxError as error:
        raise ExpressionError(f"syntax error: {error.msg}") from None

    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(
                f"{type(node).__name__} is not allowed in an expression"
            )

        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, float)) or isinstance(node.value, bool):
                # `bool` is a subclass of `int`, so it passes the numeric check and must be excluded explicitly.
                raise ExpressionError("only numeric literals are allowed")

        if isinstance(node, ast.Name):
            if node.id in _FUNCTIONS:
                continue
            if node.id not in allowed_names:
                raise ExpressionError(
                    f"{node.id!r} is not one of this widget's controls"
                )

        if isinstance(node, ast.Call):
            # The callee must be a bare name from the six.
            if not isinstance(node.func, ast.Name) or node.func.id not in _FUNCTIONS:
                raise ExpressionError("only min, max, round, abs, floor and ceil may be called")
            if node.keywords:
                raise ExpressionError("keyword arguments are not allowed")
            if len(node.args) > 3:
                raise ExpressionError("too many arguments")

        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Pow):
            exponent = node.right
            if isinstance(exponent, ast.UnaryOp) and isinstance(exponent.op, ast.USub):
                exponent = exponent.operand
            if not isinstance(exponent, ast.Constant) or not isinstance(
                exponent.value, (int, float)
            ):
                raise ExpressionError("an exponent must be a numeric literal")
            if abs(exponent.value) > MAX_EXPONENT:
                raise ExpressionError(f"an exponent may not exceed {MAX_EXPONENT}")

    return tree


def evaluate(tree: ast.Expression, variables: Mapping[str, float]) -> float:
    """Walk the validated tree."""

    def walk(node: ast.AST) -> float:
        if isinstance(node, ast.Expression):
            return walk(node.body)
        if isinstance(node, ast.Constant):
            return float(node.value)  # type: ignore[arg-type]
        if isinstance(node, ast.Name):
            try:
                return float(variables[node.id])
            except KeyError:
                raise ExpressionError(f"{node.id!r} has no value") from None
        if isinstance(node, ast.UnaryOp):
            operand = walk(node.operand)
            return -operand if isinstance(node.op, ast.USub) else +operand
        if isinstance(node, ast.BinOp):
            left, right = walk(node.left), walk(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            if isinstance(node.op, ast.Div):
                if right == 0:
                    raise ExpressionError("division by zero")
                return left / right
            if isinstance(node.op, ast.Pow):
                return left ** right
        if isinstance(node, ast.Call):
            name = node.func.id  # type: ignore[union-attr]
            return float(_FUNCTIONS[name](*[walk(arg) for arg in node.args]))
        raise ExpressionError(  # pragma: no cover - `parse` rejects these first
            f"{type(node).__name__} reached the evaluator"
        )

    return walk(tree)


def check(source: str, controls: Mapping[str, Any]) -> str | None:
    """Static check plus a domain sweep."""
    import itertools

    names = set(controls)
    try:
        tree = parse(source, names)
    except ExpressionError as error:
        return str(error)

    if not names:
        return "an expression needs at least one control"

    ordered = sorted(names)
    axes = []
    for name in ordered:
        control = controls[name]
        low, high = float(control.min), float(control.max)
        axes.append([low, (low + high) / 2, high])

    for point in itertools.product(*axes):
        assignment = dict(zip(ordered, point))
        try:
            value = evaluate(tree, assignment)
        except ExpressionError as error:
            return f"{error} at {assignment}"
        except (ArithmeticError, OverflowError, ValueError) as error:
            return f"{type(error).__name__} at {assignment}: {error}"

        if value != value:
            return f"produced NaN at {assignment}"
        if math.isinf(value):
            return f"produced infinity at {assignment}"
        if abs(value) > MAX_MAGNITUDE:
            return f"produced an implausible magnitude at {assignment}"
        if value < 0:
            # A simulator's output is money or a count.
            return f"produced a negative result at {assignment}"

    return None
