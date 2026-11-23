from dataclasses import dataclass
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UsageEvent
from app.services.costs import compute_cost, price_snapshot

SOURCE_CHAT = "chat"
SOURCE_WORKFLOW = "workflow"
SOURCE_COLLABORATION = "collaboration"
SOURCE_ARENA = "arena"
SOURCE_PROMPT_LAB = "prompt_lab"
SOURCE_MODEL_EVAL = "model_eval"
SOURCE_AGENT_BUILDER = "agent_builder"
SOURCE_KNOWLEDGE_RETRIEVAL = "knowledge_retrieval"
ALLOWED_SOURCES = frozenset(
    {
        SOURCE_CHAT,
        SOURCE_WORKFLOW,
        SOURCE_COLLABORATION,
        SOURCE_ARENA,
        SOURCE_PROMPT_LAB,
        SOURCE_MODEL_EVAL,
        SOURCE_AGENT_BUILDER,
        SOURCE_KNOWLEDGE_RETRIEVAL,
    }
)


@dataclass(frozen=True, slots=True)
class WrittenUsage:
    event: UsageEvent
    cost: float
    unpriced: bool


async def _has_event(
    session: AsyncSession,
    *,
    message_id: UUID | None,
    workflow_node_run_id: UUID | None,
    collaboration_step_id: UUID | None,
    source_ref_id: UUID | None,
) -> bool:
    if message_id is not None:
        condition = UsageEvent.message_id == message_id
    elif workflow_node_run_id is not None:
        condition = UsageEvent.workflow_node_run_id == workflow_node_run_id
    elif collaboration_step_id is not None:
        condition = UsageEvent.collaboration_step_id == collaboration_step_id
    elif source_ref_id is not None:
        condition = UsageEvent.source_ref_id == source_ref_id
    else:
        return False
    found = await session.execute(select(UsageEvent.id).where(condition).limit(1))
    return found.scalar_one_or_none() is not None


async def write_usage_event(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    source: str,
    provider_id: str | None,
    model: str | None,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    conversation_id: UUID | None = None,
    message_id: UUID | None = None,
    api_key_id: UUID | None = None,
    workflow_node_run_id: UUID | None = None,
    collaboration_step_id: UUID | None = None,
    source_ref_id: UUID | None = None,
) -> WrittenUsage | None:
    """Append one ledger row per billable LLM call.

    Returns ``None`` when the same message/node/step was already recorded, which makes
    finalizers and runner retries idempotent.
    """
    if source not in ALLOWED_SOURCES:
        raise ValueError(f"unknown usage source: {source}")
    if workflow_node_run_id == UUID(int=0):
        workflow_node_run_id = None
    if collaboration_step_id == UUID(int=0):
        collaboration_step_id = None
    if await _has_event(
        session,
        message_id=message_id,
        workflow_node_run_id=workflow_node_run_id,
        collaboration_step_id=collaboration_step_id,
        source_ref_id=source_ref_id,
    ):
        return None

    input_price, output_price = await price_snapshot(session, provider_id, model)
    cost = compute_cost(prompt_tokens, completion_tokens, input_price, output_price)
    unpriced = input_price is None or output_price is None
    event = UsageEvent(
        workspace_id=workspace_id,
        user_id=user_id,
        conversation_id=conversation_id,
        message_id=message_id,
        source=source,
        source_ref_id=source_ref_id,
        api_key_id=api_key_id,
        workflow_node_run_id=workflow_node_run_id,
        collaboration_step_id=collaboration_step_id,
        provider_id=provider_id,
        model=model,
        prompt_tokens=prompt_tokens,
        completion_tokens=completion_tokens,
        input_price=input_price,
        output_price=output_price,
        cost=cost,
        unpriced=unpriced,
    )
    session.add(event)
    await session.flush()
    return WrittenUsage(event=event, cost=cost, unpriced=unpriced)
