from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.embedding import EmbeddingProvider
from app.services.retrieval import retrieve_chunks


@dataclass(frozen=True, slots=True)
class EvalQuestion:
    question: str
    relevant_document_ids: frozenset[UUID]


@dataclass(frozen=True, slots=True)
class EvalReport:
    total: int
    hits: int

    @property
    def recall(self) -> float:
        return self.hits / self.total if self.total else 0.0


async def evaluate_recall(
    session: AsyncSession,
    *,
    user_id: UUID,
    kb_id: UUID,
    questions: Sequence[EvalQuestion],
    top_k: int,
    embedder: EmbeddingProvider,
) -> EvalReport:
    """Document-level Recall@k over a labelled question set."""
    hits = 0
    for item in questions:
        results = await retrieve_chunks(
            session,
            user_id=user_id,
            kb_id=kb_id,
            query=item.question,
            top_k=top_k,
            embedder=embedder,
        )
        if any(result.document_id in item.relevant_document_ids for result in results):
            hits += 1
    return EvalReport(total=len(questions), hits=hits)
