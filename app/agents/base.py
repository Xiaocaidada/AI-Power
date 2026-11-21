from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class AgentSpec:
    name: str
    system_prompt: str
    tools: tuple[str, ...] = ()
