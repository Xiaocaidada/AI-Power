from app.tools.base import ToolRegistry
from app.tools.calculator import build_calculator_tool
from app.tools.current_time import build_current_time_tool
from app.tools.kb_search import build_kb_search_tool


def build_tool_registry() -> ToolRegistry:
    return ToolRegistry(
        [
            build_current_time_tool(),
            build_kb_search_tool(),
            build_calculator_tool(),
        ]
    )
