from app.tools.base import ToolRegistry
from app.tools.current_time import build_current_time_tool


def build_tool_registry() -> ToolRegistry:
    """Tools available to agents. `kb_search` and `calculator` arrive in P3-S2."""
    return ToolRegistry([build_current_time_tool()])
