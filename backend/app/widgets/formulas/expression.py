"""The escape hatch, and why it is barely one.

Sometimes a widget needs a shape the registry does not cover -- "half of what
you save, plus five dollars". Rather than adding a formula per lesson, a
simulator may carry a short arithmetic expression over its own control names.

Everything in this file exists to make that safe, because a string from a
language model, evaluated, is the oldest hole in the book.

## Never `eval`. Never `exec`. Never a library.

Not "eval with a restricted `__builtins__`" -- that has been broken publicly
many times, most simply through `().__class__.__bases__[0].__subclasses__()`,
which needs no builtins at all. Not `asteval`, `simpleeval` or `numexpr`, each
of which is a dependency whose security is somebody else's ongoing project.

This walks the AST itself and rejects every node type that is not on a short
allowlist. The allowlist is the security boundary, and it is a whitelist rather
than a blacklist for the usual reason: a blacklist is a list of the attacks
somebody thought of.

## What is allowed

Numeric literals, names that were declared as controls, `+ - * / **`, unary
`+ -`, and calls to exactly six functions: `min`, `max`, `round`, `abs`,
`floor`, `ceil`. That is arithmetic. It is not a language.

Notably absent, each for a concrete reason:

  * **Attribute access** (`x.y`) -- the whole sandbox-escape family lives here.
  * **Subscripting** (`x[y]`) -- same, via `__globals__` and friends.
  * **Comprehensions and lambdas** -- they introduce scopes and can loop.
  * **Strings** -- there is nothing arithmetic to do with one, and `'a'*10**9`
    is a memory exhaustion in four characters.
  * **`**` with a large exponent** -- allowed as an operator, bounded as a
    value: see `MAX_EXPONENT`.

## And it is still evaluated before it ships

Passing the AST check is necessary and not sufficient. `check()` also evaluates
the expression at every corner and midpoint of the control box and rejects NaN,
infinity, and results outside a sane magnitude. An expression that divides by
`(x - 5)` is syntactically perfect and explodes when a child drags the slider
to 5.
"""

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

#: The only callables. Bound to real implementations here rather than looked up
#: in a namespace at evaluation time, so there is no namespace to poison.
_FUNCTIONS: dict[str, Callable[..., float]] = {
    "min": min,
    "max": max,
    "round": round,
    "abs": abs,
    "floor": math.floor,
    "ceil": math.ceil,
}

#: `2 ** 10000` is a valid arithmetic expression and a denial of service. The
#: bound is on the exponent's literal value, checked statically, because by the
#: time it is being computed it is too late.
MAX_EXPONENT = 64

#: Results beyond this are not a savings lesson. Same ceiling the registry uses.
MAX_MAGNITUDE = 1e11

#: How long an expression may be. A short cap is itself a control: nothing this
#: is for needs 200 characters.
MAX_LENGTH = 200


class ExpressionError(ValueError):
    """The expression is not acceptable. Carries a human-readable reason."""


def parse(source: str, allowed_names: set[str]) -> ast.Expression:
    """Parse and validate, or raise `ExpressionError`.

    Separate from evaluation so that the static check can be run once, at
    validation time, and the (much cheaper) evaluation can be repeated for every
    probe point without re-walking the tree.
    """
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
                # `bool` is a subclass of `int`, so it passes the numeric check
                # and must be excluded explicitly. `True * 10` is not arithmetic
                # anybody meant to write.
                raise ExpressionError("only numeric literals are allowed")

        if isinstance(node, ast.Name):
            if node.id in _FUNCTIONS:
                continue
            if node.id not in allowed_names:
                raise ExpressionError(
                    f"{node.id!r} is not one of this widget's controls"
                )

        if isinstance(node, ast.Call):
            # The callee must be a bare name from the six. `f(x)(y)` and
            # `obj.f(x)` are both rejected here, and `ast.Attribute` is not on
            # the node allowlist anyway -- belt and braces on the one place an
            # escape would be most valuable.
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
    """Walk the validated tree. No `eval`, no namespace, no builtins.

    A recursive descent over the eight node types that survived `parse`. It is
    twenty lines because there is nothing else in the language to support -- and
    that is the point: an evaluator small enough to read is an evaluator small
    enough to be sure about.
    """

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
    """Static check plus a domain sweep. Returns a problem, or None if it is safe.

    This is gate 5's expression half. It evaluates at every corner and midpoint
    of the control box -- 3^k points -- and rejects anything that is not a
    finite, plausible number everywhere. An expression that only misbehaves at
    one extreme is the one a child will find.
    """
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
            # A simulator's output is money or a count. Neither is negative, and
            # an expression that can go negative is one whose lesson breaks at
            # the point it does.
            return f"produced a negative result at {assignment}"

    return None
