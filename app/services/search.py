from typing import Any
from uuid import UUID

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Conversation,
    CustomAgent,
    Document,
    KnowledgeBase,
    Message,
    Project,
    PromptTemplate,
    PromptVersion,
)

RESULT_LIMIT = 5


def _like(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


async def global_search(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    query: str,
) -> list[dict[str, Any]]:
    term = _like(query)
    results: list[dict[str, Any]] = []

    conversations = list(
        (
            await session.execute(
                select(Conversation)
                .where(
                    Conversation.workspace_id == workspace_id,
                    Conversation.archived_at.is_(None),
                    or_(
                        Conversation.title.ilike(term, escape="\\"),
                        exists(
                            select(Message.id).where(
                                Message.conversation_id == Conversation.id,
                                Message.content.ilike(term, escape="\\"),
                            )
                        ),
                    ),
                )
                .order_by(Conversation.updated_at.desc())
                .limit(RESULT_LIMIT)
            )
        ).scalars()
    )
    for conversation in conversations:
        results.append(
            {
                "type": "conversation",
                "id": str(conversation.id),
                "title": conversation.title or "New conversation",
                "subtitle": f"{conversation.provider_id} · {conversation.model}",
                "href": f"/chat/{conversation.id}",
            }
        )

    projects = list(
        (
            await session.execute(
                select(Project)
                .where(
                    Project.workspace_id == workspace_id,
                    Project.archived_at.is_(None),
                    or_(
                        Project.name.ilike(term, escape="\\"),
                        Project.description.ilike(term, escape="\\"),
                        Project.instructions.ilike(term, escape="\\"),
                    ),
                )
                .order_by(Project.updated_at.desc())
                .limit(RESULT_LIMIT)
            )
        ).scalars()
    )
    for project in projects:
        results.append(
            {
                "type": "project",
                "id": str(project.id),
                "title": project.name,
                "subtitle": project.description or "Project",
                "href": f"/projects/{project.id}",
            }
        )

    agents = list(
        (
            await session.execute(
                select(CustomAgent)
                .where(
                    CustomAgent.workspace_id == workspace_id,
                    CustomAgent.archived_at.is_(None),
                    or_(
                        CustomAgent.owner_user_id == user_id,
                        CustomAgent.visibility == "shared",
                    ),
                    or_(
                        CustomAgent.name.ilike(term, escape="\\"),
                        CustomAgent.description.ilike(term, escape="\\"),
                        CustomAgent.instructions.ilike(term, escape="\\"),
                    ),
                )
                .order_by(CustomAgent.updated_at.desc())
                .limit(RESULT_LIMIT)
            )
        ).scalars()
    )
    for agent in agents:
        results.append(
            {
                "type": "agent",
                "id": str(agent.id),
                "title": agent.name,
                "subtitle": agent.description or agent.category,
                "href": f"/agents/{agent.id}",
            }
        )

    prompts = list(
        (
            await session.execute(
                select(PromptTemplate)
                .where(
                    PromptTemplate.workspace_id == workspace_id,
                    PromptTemplate.deleted_at.is_(None),
                    or_(
                        PromptTemplate.name.ilike(term, escape="\\"),
                        PromptTemplate.description.ilike(term, escape="\\"),
                        exists(
                            select(PromptVersion.id).where(
                                PromptVersion.template_id == PromptTemplate.id,
                                PromptVersion.system_prompt.ilike(term, escape="\\"),
                            )
                        ),
                    ),
                )
                .order_by(PromptTemplate.created_at.desc())
                .limit(RESULT_LIMIT)
            )
        ).scalars()
    )
    for prompt in prompts:
        results.append(
            {
                "type": "prompt",
                "id": str(prompt.id),
                "title": prompt.name,
                "subtitle": f"{prompt.category} · prompt",
                "href": "/settings/prompts",
            }
        )

    kbs = list(
        (
            await session.execute(
                select(KnowledgeBase)
                .where(
                    KnowledgeBase.workspace_id == workspace_id,
                    KnowledgeBase.deleted_at.is_(None),
                    KnowledgeBase.name.ilike(term, escape="\\"),
                )
                .order_by(KnowledgeBase.created_at.desc())
                .limit(RESULT_LIMIT)
            )
        ).scalars()
    )
    for kb in kbs:
        results.append(
            {
                "type": "knowledge_base",
                "id": str(kb.id),
                "title": kb.name,
                "subtitle": "Knowledge base",
                "href": f"/knowledge/{kb.id}",
            }
        )

    documents = (
        await session.execute(
            select(Document, KnowledgeBase.name)
            .join(KnowledgeBase, KnowledgeBase.id == Document.kb_id)
            .where(
                Document.workspace_id == workspace_id,
                Document.deleted_at.is_(None),
                KnowledgeBase.deleted_at.is_(None),
                Document.filename.ilike(term, escape="\\"),
            )
            .order_by(Document.created_at.desc())
            .limit(RESULT_LIMIT)
        )
    ).all()
    for document, kb_name in documents:
        results.append(
            {
                "type": "file",
                "id": str(document.id),
                "title": document.filename,
                "subtitle": f"{kb_name} · {document.status}",
                "href": f"/knowledge/{document.kb_id}",
            }
        )

    return results