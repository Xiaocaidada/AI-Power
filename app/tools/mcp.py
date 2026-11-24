"""MCP tool reference helpers shared by Agent configuration and runtime."""

from uuid import UUID

MCP_TOOL_PREFIX = "mcp:"


def format_mcp_tool(server_id: UUID, tool_name: str) -> str:
    return f"{MCP_TOOL_PREFIX}{server_id}:{tool_name}"


def parse_mcp_tool_ref(reference: str) -> tuple[UUID, str] | None:
    if not reference.startswith(MCP_TOOL_PREFIX):
        return None
    parts = reference.split(":", 2)
    if len(parts) != 3 or not parts[2]:
        return None
    try:
        server_id = UUID(parts[1])
    except ValueError:
        return None
    return server_id, parts[2]