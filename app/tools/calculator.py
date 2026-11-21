import ast

from pydantic import BaseModel, Field

from app.tools.base import ToolContext, ToolError, ToolSpec

MAX_EXPRESSION_CHARS = 200
MAX_NODES = 50
MAX_ABS_EXPONENT = 12
MAX_ABS_RESULT = 1e12

_ALLOWED_BINOPS = (ast.Add, ast.Sub, ast.Mult, ast.Div, ast.FloorDiv, ast.Mod, ast.Pow)
_ALLOWED_UNARY = (ast.UAdd, ast.USub)


class CalculatorArgs(BaseModel):
    expression: str = Field(min_length=1, max_length=1000)


async def calculate(context: ToolContext, args: CalculatorArgs) -> str:
    expression = args.expression.strip()
    if len(expression) > MAX_EXPRESSION_CHARS:
        raise ToolError("invalid_expression", "Expression is too long")
    try:
        tree = ast.parse(expression, mode="eval")
    except SyntaxError:
        raise ToolError("invalid_expression", "Expression is not valid arithmetic") from None
    if sum(1 for _ in ast.walk(tree)) > MAX_NODES:
        raise ToolError("invalid_expression", "Expression is too complex")
    value = _evaluate(tree.body)
    return _format(value)


def _evaluate(node: ast.AST) -> float:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
            raise ToolError("invalid_expression", "Only numbers are allowed")
        return float(node.value)
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, _ALLOWED_UNARY):
        value = _evaluate(node.operand)
        return value if isinstance(node.op, ast.UAdd) else -value
    if isinstance(node, ast.BinOp) and isinstance(node.op, _ALLOWED_BINOPS):
        return _apply(node.op, _evaluate(node.left), _evaluate(node.right))
    raise ToolError("invalid_expression", "Unsupported expression")


def _apply(operator: ast.operator, left: float, right: float) -> float:
    if isinstance(operator, ast.Pow):
        if abs(right) > MAX_ABS_EXPONENT:
            raise ToolError("invalid_expression", "Exponent is too large")
        if left == 0 and right < 0:
            raise ToolError("calculation_error", "Division by zero")
    try:
        if isinstance(operator, ast.Add):
            result = left + right
        elif isinstance(operator, ast.Sub):
            result = left - right
        elif isinstance(operator, ast.Mult):
            result = left * right
        elif isinstance(operator, ast.Div):
            result = left / right
        elif isinstance(operator, ast.FloorDiv):
            result = float(left // right)
        elif isinstance(operator, ast.Mod):
            result = left % right
        else:
            result = left**right
    except ZeroDivisionError:
        raise ToolError("calculation_error", "Division by zero") from None
    if abs(result) > MAX_ABS_RESULT:
        raise ToolError("invalid_expression", "Result is too large")
    return result


def _format(value: float) -> str:
    rounded = round(value, 10)
    if rounded.is_integer():
        return str(int(rounded))
    return str(rounded)


def build_calculator_tool() -> ToolSpec:
    return ToolSpec(
        name="calculator",
        description=(
            "Evaluate a safe arithmetic expression with numbers, parentheses, "
            "+ - * / // % and ** (exponent <= 12)."
        ),
        args_model=CalculatorArgs,
        handler=calculate,
    )
