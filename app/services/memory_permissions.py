"""Permission matrix for project and Agent access to long-term memory."""

from dataclasses import dataclass
from uuid import UUID

from app.models import CustomAgent, Project

READ_SCOPES = frozenset({"global", "project", "agent"})
WRITE_SCOPES = frozenset({"global", "project", "agent"})
WRITE_MODES = frozenset({"candidate", "create", "upsert"})

DEFAULT_AGENT_PERMISSIONS: dict[str, object] = {
    "read_global": True,
    "read_project": True,
    "read_agent": True,
    "write": False,
    "write_scope": "agent",
    "write_mode": "candidate",
}
DEFAULT_PROJECT_PERMISSIONS: dict[str, object] = {
    "enabled": None,
    "allow_global": True,
    "allow_agent_writes": False,
}


@dataclass(frozen=True, slots=True)
class MemoryAccess:
    read_scopes: frozenset[str]
    write: bool
    write_scope: str
    write_mode: str
    agent_id: UUID | None = None
    project_id: UUID | None = None

    def can_read(self, scope_type: str) -> bool:
        return scope_type in self.read_scopes


def normalize_agent_permissions(
    raw: dict[str, object] | None, memory_enabled: bool
) -> dict[str, object]:
    values = {**DEFAULT_AGENT_PERMISSIONS, **(raw or {})}
    result: dict[str, object] = {
        "read_global": bool(values["read_global"]),
        "read_project": bool(values["read_project"]),
        "read_agent": bool(values["read_agent"]),
        "write": bool(values["write"]),
        "write_scope": str(values["write_scope"]),
        "write_mode": str(values["write_mode"]),
    }
    if result["write_scope"] not in WRITE_SCOPES:
        result["write_scope"] = "agent"
    if result["write_mode"] not in WRITE_MODES:
        result["write_mode"] = "candidate"
    if not memory_enabled:
        result["write"] = False
    return result


def normalize_project_permissions(
    raw: dict[str, object] | None,
) -> dict[str, object]:
    values = {**DEFAULT_PROJECT_PERMISSIONS, **(raw or {})}
    enabled = values.get("enabled")
    return {
        "enabled": None if enabled is None else bool(enabled),
        "allow_global": bool(values["allow_global"]),
        "allow_agent_writes": bool(values["allow_agent_writes"]),
    }


def agent_memory_access(agent: CustomAgent) -> MemoryAccess:
    permissions = normalize_agent_permissions(
        agent.memory_permissions, agent.memory_enabled
    )
    scopes: set[str] = set()
    if agent.memory_enabled:
        if permissions["read_global"]:
            scopes.add("global")
        if permissions["read_project"]:
            scopes.add("project")
        if permissions["read_agent"]:
            scopes.add("agent")
    return MemoryAccess(
        read_scopes=frozenset(scopes),
        write=bool(permissions["write"]),
        write_scope=str(permissions["write_scope"]),
        write_mode=str(permissions["write_mode"]),
        agent_id=agent.id,
    )


def project_memory_allowed(project: Project) -> bool | None:
    return normalize_project_permissions(project.memory_permissions)["enabled"]


def project_allows_global(project: Project) -> bool:
    return bool(normalize_project_permissions(project.memory_permissions)["allow_global"])


def project_allows_agent_writes(project: Project) -> bool:
    return bool(
        normalize_project_permissions(project.memory_permissions)["allow_agent_writes"]
    )