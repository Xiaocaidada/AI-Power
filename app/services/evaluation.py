import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy.ext.asyncio import AsyncSession

from app.providers.embedding import EmbeddingProvider
from app.services.retrieval import retrieve_chunks

EVAL_NAMESPACE = uuid5(NAMESPACE_URL, "https://ai-power.local/eval")


def document_id_for(filename: str) -> UUID:
    """Deterministic document ID so eval labels stay valid across rebuilds."""
    return uuid5(EVAL_NAMESPACE, f"document/{filename}")


@dataclass(frozen=True, slots=True)
class EvalDocument:
    filename: str
    text: str


@dataclass(frozen=True, slots=True)
class EvalQuestion:
    question: str
    relevant_document_ids: frozenset[UUID]


def load_eval_dataset(path: Path) -> tuple[list[EvalDocument], list[EvalQuestion]]:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    documents = [
        EvalDocument(filename=str(item["filename"]), text=str(item["text"]))
        for item in raw.get("documents", [])
    ]
    filenames = [document.filename for document in documents]
    if len(set(filenames)) != len(filenames):
        raise ValueError("duplicate document filename in eval dataset")
    known = set(filenames)

    questions: list[EvalQuestion] = []
    seen: set[str] = set()
    for item in raw.get("questions", []):
        text = str(item["question"]).strip()
        if not text:
            raise ValueError("empty question in eval dataset")
        if text in seen:
            raise ValueError(f"duplicate question in eval dataset: {text}")
        seen.add(text)
        relevant = [str(filename) for filename in item["relevant_filenames"]]
        unknown = sorted(set(relevant) - known)
        if unknown:
            raise ValueError(f"unknown document reference in eval dataset: {unknown}")
        questions.append(
            EvalQuestion(
                question=text,
                relevant_document_ids=frozenset(document_id_for(name) for name in relevant),
            )
        )
    return documents, questions


def render_questions_jsonl(questions: Sequence[EvalQuestion]) -> str:
    lines = [
        json.dumps(
            {
                "question": item.question,
                "relevant_document_ids": sorted(
                    str(document_id) for document_id in item.relevant_document_ids
                ),
            },
            ensure_ascii=False,
        )
        for item in questions
    ]
    return "\n".join(lines) + "\n"


@dataclass(frozen=True, slots=True)
class EvalReport:
    total: int
    hits: int
    missed: tuple[str, ...] = ()

    @property
    def recall(self) -> float:
        return self.hits / self.total if self.total else 0.0


async def evaluate_recall(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    kb_id: UUID,
    questions: Sequence[EvalQuestion],
    top_k: int,
    embedder: EmbeddingProvider,
) -> EvalReport:
    """Document-level Recall@k over a labelled question set."""
    hits = 0
    missed: list[str] = []
    for item in questions:
        results = await retrieve_chunks(
            session,
            workspace_id=workspace_id,
            kb_id=kb_id,
            query=item.question,
            top_k=top_k,
            embedder=embedder,
        )
        if any(result.document_id in item.relevant_document_ids for result in results):
            hits += 1
        else:
            missed.append(item.question)
    return EvalReport(total=len(questions), hits=hits, missed=tuple(missed))
