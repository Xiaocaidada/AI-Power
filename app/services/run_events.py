import json
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import SessionLocal
from app.models import CollaborationRunEvent, WorkflowRunEvent

TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled"})
TERMINAL_EVENTS = frozenset({"workflow_end", "collaboration_end"})
POLL_INTERVAL_SECONDS = 0.3
KEEPALIVE_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class RunEvent:
    seq: int
    event: str
    payload: dict[str, object]
    created_at: datetime


def format_sse(event: RunEvent) -> str:
    body = json.dumps(event.payload, ensure_ascii=False)
    return f"id: {event.seq}\nevent: {event.event}\ndata: {body}\n\n"


async def _append(
    model: type[WorkflowRunEvent] | type[CollaborationRunEvent],
    run_id: UUID,
    event: str,
    payload: dict[str, object],
) -> int:
    async with SessionLocal() as session:
        current = (
            await session.execute(
                select(func.coalesce(func.max(model.seq), 0)).where(model.run_id == run_id)
            )
        ).scalar_one()
        seq = int(current) + 1
        session.add(model(run_id=run_id, seq=seq, event=event, payload=payload))
        await session.commit()
        return seq


async def append_workflow_event(run_id: UUID, event: str, payload: dict[str, object]) -> int:
    return await _append(WorkflowRunEvent, run_id, event, payload)


async def append_collaboration_event(run_id: UUID, event: str, payload: dict[str, object]) -> int:
    return await _append(CollaborationRunEvent, run_id, event, payload)


async def _list(
    session: AsyncSession,
    model: type[WorkflowRunEvent] | type[CollaborationRunEvent],
    run_id: UUID,
    after: int,
) -> list[RunEvent]:
    rows = (
        await session.execute(
            select(model).where(model.run_id == run_id, model.seq > after).order_by(model.seq)
        )
    ).scalars()
    return [
        RunEvent(seq=row.seq, event=row.event, payload=dict(row.payload), created_at=row.created_at)
        for row in rows
    ]


async def list_workflow_events(
    session: AsyncSession, run_id: UUID, after: int = 0
) -> list[RunEvent]:
    return await _list(session, WorkflowRunEvent, run_id, after)


async def list_collaboration_events(
    session: AsyncSession, run_id: UUID, after: int = 0
) -> list[RunEvent]:
    return await _list(session, CollaborationRunEvent, run_id, after)
