"""Restricted expression evaluator for workflow ``code`` nodes.

This is deliberately not a Python interpreter: only literals, safe operators,
subscripts, f-strings and a small whitelist of builtins/methods are evaluated.
There is no attribute traversal, import, assignment, loop or function creation.
"""

import ast
import json
import operator
from typing import Any

MAX_CODE_CHARS = 5000
MAX_AST_NODES = 200
MAX_DEPTH = 40
MAX_STRING_CHARS = 20000
MAX_COLLECTION_ITEMS = 1000
MAX_POW_EXPONENT = 1000

BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
    ast.Not: operator.not_,
}
COMPARE_OPS = {
    ast.Eq: operator.eq,
    ast.NotEq: operator.ne,
    ast.Lt: operator.lt,
    ast.LtE: operator.le,
    ast.Gt: operator.gt,
    ast.GtE: operator.ge,
    ast.In: lambda left, right: left in right,
    ast.NotIn: lambda left, right: left not in right,
    ast.Is: operator.is_,
    ast.IsNot: operator.is_not,
}


class SandboxError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


class _JsonNamespace:
    @staticmethod
    def loads(value: str) -> Any:
        return json.loads(value)

    @staticmethod
    def dumps(value: Any) -> str:
        return json.dumps(value, ensure_ascii=False)


JSON_NAMESPACE = _JsonNamespace()

STR_METHODS = {
    "strip",
    "lstrip",
    "rstrip",
    "lower",
    "upper",
    "title",
    "casefold",
    "replace",
    "split",
    "rsplit",
    "splitlines",
    "join",
    "startswith",
    "endswith",
    "find",
    "rfind",
    "count",
    "zfill",
    "ljust",
    "rjust",
    "center",
    "removeprefix",
    "removesuffix",
}
LIST_METHODS = {"count", "index"}
DICT_METHODS = {"get", "keys", "values", "items"}

SAFE_FUNCTIONS: dict[str, Any] = {
    "len": len,
    "str": str,
    "int": int,
    "float": float,
    "round": round,
    "min": min,
    "max": max,
    "sorted": sorted,
    "sum": sum,
    "abs": abs,
    "bool": bool,
    "list": list,
    "dict": dict,
    "json_loads": json.loads,
    "json_dumps": lambda value: json.dumps(value, ensure_ascii=False),
}


def _iter_nodes(node: ast.AST) -> int:
    count = 0
    for _ in ast.walk(node):
        count += 1
        if count > MAX_AST_NODES:
            raise SandboxError("code_too_complex", "Expression is too complex")
    return count


def _check_string(value: str) -> str:
    if len(value) > MAX_STRING_CHARS:
        raise SandboxError("code_output_too_large", "String value is too large")
    return value


def _check_collection(value: Any) -> Any:
    if isinstance(value, (list, tuple, dict)) and len(value) > MAX_COLLECTION_ITEMS:
        raise SandboxError("code_output_too_large", "Collection is too large")
    return value


def _allowed_methods(base: Any) -> set[str]:
    if isinstance(base, str):
        return STR_METHODS
    if isinstance(base, (list, tuple)):
        return LIST_METHODS
    if isinstance(base, dict):
        return DICT_METHODS
    if isinstance(base, _JsonNamespace):
        return {"loads", "dumps"}
    return set()


def _call_method(base: Any, name: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
    if name.startswith("_") or name not in _allowed_methods(base):
        raise SandboxError("code_forbidden", f"Method {name!r} is not allowed")
    method = getattr(base, name)
    result = method(*args, **kwargs)
    if isinstance(result, str):
        return _check_string(result)
    return _check_collection(result)


def _eval(node: ast.AST, variables: dict[str, Any], depth: int) -> Any:
    if depth > MAX_DEPTH:
        raise SandboxError("code_too_complex", "Expression is nested too deeply")
    depth += 1
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, (str, int, float, bool)) or value is None:
            return _check_string(value) if isinstance(value, str) else value
        raise SandboxError("code_forbidden", "Unsupported literal")
    if isinstance(node, ast.Name):
        if node.id.startswith("_") or node.id not in variables:
            raise SandboxError("code_unknown_variable", f"Unknown variable {node.id!r}")
        return variables[node.id]
    if isinstance(node, ast.BinOp):
        op = BIN_OPS.get(type(node.op))
        if op is None:
            raise SandboxError("code_forbidden", "Operator is not allowed")
        left = _eval(node.left, variables, depth)
        right = _eval(node.right, variables, depth)
        if isinstance(node.op, ast.Pow):
            if not isinstance(right, (int, float)) or abs(right) > MAX_POW_EXPONENT:
                raise SandboxError("code_forbidden", "Exponent is too large")
        result = op(left, right)
        return (
            _check_string(result) if isinstance(result, str) else _check_collection(result)
        )
    if isinstance(node, ast.UnaryOp):
        op = UNARY_OPS.get(type(node.op))
        if op is None:
            raise SandboxError("code_forbidden", "Operator is not allowed")
        return op(_eval(node.operand, variables, depth))
    if isinstance(node, ast.BoolOp):
        is_and = isinstance(node.op, ast.And)
        result: Any = True if is_and else False
        for value_node in node.values:
            result = _eval(value_node, variables, depth)
            if is_and and not result:
                return result
            if not is_and and result:
                return result
        return result
    if isinstance(node, ast.Compare):
        left = _eval(node.left, variables, depth)
        for op_node, comparator in zip(node.ops, node.comparators, strict=False):
            op = COMPARE_OPS.get(type(op_node))
            if op is None:
                raise SandboxError("code_forbidden", "Comparison is not allowed")
            right = _eval(comparator, variables, depth)
            if not op(left, right):
                return False
            left = right
        return True
    if isinstance(node, ast.IfExp):
        return _eval(
            node.body if _eval(node.test, variables, depth) else node.orelse,
            variables,
            depth,
        )
    if isinstance(node, (ast.List, ast.Tuple)):
        items = [_eval(item, variables, depth) for item in node.elts]
        if len(items) > MAX_COLLECTION_ITEMS:
            raise SandboxError("code_output_too_large", "Collection is too large")
        return items if isinstance(node, ast.List) else tuple(items)
    if isinstance(node, ast.Dict):
        result: dict[Any, Any] = {}
        for key_node, value_node in zip(node.keys, node.values, strict=False):
            if key_node is None:
                raise SandboxError("code_forbidden", "Dict unpacking is not allowed")
            result[_eval(key_node, variables, depth)] = _eval(
                value_node, variables, depth
            )
        if len(result) > MAX_COLLECTION_ITEMS:
            raise SandboxError("code_output_too_large", "Collection is too large")
        return result
    if isinstance(node, ast.Subscript):
        base = _eval(node.value, variables, depth)
        index = _eval(node.slice, variables, depth)
        try:
            result = base[index]
        except (KeyError, IndexError, TypeError):
            raise SandboxError("code_error", "Subscript is out of range") from None
        return (
            _check_string(result) if isinstance(result, str) else _check_collection(result)
        )
    if isinstance(node, ast.Slice):
        return slice(
            _eval(node.lower, variables, depth) if node.lower else None,
            _eval(node.upper, variables, depth) if node.upper else None,
            _eval(node.step, variables, depth) if node.step else None,
        )
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for value in node.values:
            if isinstance(value, ast.Constant):
                parts.append(str(value.value))
            elif isinstance(value, ast.FormattedValue):
                parts.append(str(_eval(value.value, variables, depth)))
            else:
                raise SandboxError("code_forbidden", "Unsupported f-string part")
        return _check_string("".join(parts))
    if isinstance(node, ast.Call):
        return _eval_call(node, variables, depth)
    if isinstance(node, ast.Attribute):
        raise SandboxError("code_forbidden", "Attribute access is not allowed")
    raise SandboxError("code_forbidden", f"Unsupported syntax: {type(node).__name__}")


def _eval_call(node: ast.Call, variables: dict[str, Any], depth: int) -> Any:
    args = [_eval(argument, variables, depth) for argument in node.args]
    kwargs = {
        keyword.arg: _eval(keyword.value, variables, depth)
        for keyword in node.keywords
        if keyword.arg is not None
    }
    if any(keyword.arg is None for keyword in node.keywords):
        raise SandboxError("code_forbidden", "Keyword unpacking is not allowed")
    if isinstance(node.func, ast.Name):
        if node.func.id.startswith("_") or node.func.id not in SAFE_FUNCTIONS:
            raise SandboxError(
                "code_forbidden", f"Function {node.func.id!r} is not allowed"
            )
        result = SAFE_FUNCTIONS[node.func.id](*args, **kwargs)
    elif isinstance(node.func, ast.Attribute):
        base = _eval(node.func.value, variables, depth)
        result = _call_method(base, node.func.attr, args, kwargs)
    else:
        raise SandboxError("code_forbidden", "Unsupported call target")
    if isinstance(result, str):
        return _check_string(result)
    return _check_collection(result)


def evaluate_expression(
    code: str, variables: dict[str, Any], *, max_output_chars: int = 20000
) -> str:
    if len(code) > MAX_CODE_CHARS:
        raise SandboxError("code_too_large", "Code is too long")
    try:
        tree = ast.parse(code.strip(), mode="eval")
    except SyntaxError as exc:
        raise SandboxError("invalid_code", f"Invalid expression: {exc.msg}") from None
    if tree.body is None:
        raise SandboxError("invalid_code", "Expression is empty")
    _iter_nodes(tree)
    scope = {**variables, "json": JSON_NAMESPACE}
    try:
        value = _eval(tree.body, scope, 0)
    except SandboxError:
        raise
    except (TypeError, ValueError, ZeroDivisionError, OverflowError) as exc:
        raise SandboxError("code_error", str(exc) or type(exc).__name__) from None
    if isinstance(value, str):
        text = value
    elif value is None:
        text = "null"
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, default=str)
        except (TypeError, ValueError):
            text = str(value)
    if len(text) > max_output_chars:
        raise SandboxError(
            "code_output_too_large",
            f"Output exceeds {max_output_chars} characters",
        )
    return text