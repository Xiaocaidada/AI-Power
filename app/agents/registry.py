from collections.abc import Sequence

from app.agents.base import AgentSpec

SUPERVISOR_AGENT = "supervisor"
DELEGATE_TOOL = "delegate_to_agent"
MAX_AGENT_DEPTH = 2

SUPERVISOR_PROMPT = (
    "You are the supervisor agent of AI Power. Decompose the user's request and delegate "
    "self-contained subtasks to specialist agents instead of guessing. "
    "Available sub-agents: retrieval (searches the workspace knowledge base) and math "
    "(performs arithmetic). When a sub-agent returns a result, use it to produce the final "
    "answer in the user's language and keep any source labels it provides."
)
RETRIEVAL_PROMPT = (
    "You are the retrieval agent. Use the tools available to you to search the workspace "
    "knowledge base. Answer only from retrieved material, mention the source labels you "
    "used, and say so when the material does not contain the answer."
)
MATH_PROMPT = (
    "You are the math agent. Use the calculator tool for arithmetic instead of computing "
    "large expressions in your head. Keep the final answer short and show the result."
)


class AgentNotFoundError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"Unknown agent: {name}")
        self.name = name


class AgentRegistry:
    def __init__(self, agents: Sequence[AgentSpec]) -> None:
        self._agents = {agent.name: agent for agent in agents}

    def get(self, name: str) -> AgentSpec:
        agent = self._agents.get(name)
        if agent is None:
            raise AgentNotFoundError(name)
        return agent

    def all(self) -> list[AgentSpec]:
        return list(self._agents.values())

    def names(self) -> list[str]:
        return list(self._agents)


def build_agent_registry() -> AgentRegistry:
    return AgentRegistry(
        [
            AgentSpec(name=SUPERVISOR_AGENT, system_prompt=SUPERVISOR_PROMPT, tools=()),
            AgentSpec(
                name="retrieval",
                system_prompt=RETRIEVAL_PROMPT,
                tools=("kb_search", "current_time"),
            ),
            AgentSpec(name="math", system_prompt=MATH_PROMPT, tools=("calculator",)),
        ]
    )
