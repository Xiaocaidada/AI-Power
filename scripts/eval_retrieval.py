"""Evaluate document-level Recall@k for the retrieval pipeline.

Dataset format (JSONL, one object per line):
    {"question": "...", "relevant_document_ids": ["<uuid>", ...]}

Usage:
    python scripts/eval_retrieval.py --dataset eval.jsonl \
        --user-id <uuid> --kb-id <uuid> --top-k 5 --min-recall 0.8
"""

import argparse
import asyncio
import json
from pathlib import Path
from uuid import UUID

from app.db import SessionLocal
from app.services.embedding_factory import build_embedder
from app.services.evaluation import EvalQuestion, evaluate_recall


def load_dataset(path: Path) -> list[EvalQuestion]:
    questions: list[EvalQuestion] = []
    lines = path.read_text(encoding="utf-8").splitlines()
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
            questions.append(
                EvalQuestion(
                    question=str(raw["question"]),
                    relevant_document_ids=frozenset(
                        UUID(str(value)) for value in raw["relevant_document_ids"]
                    ),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise SystemExit(f"{path}:{line_number}: invalid dataset line ({exc})") from None
    return questions


async def _run(args: argparse.Namespace) -> int:
    questions = load_dataset(Path(args.dataset))
    if not questions:
        raise SystemExit("dataset is empty")

    async with SessionLocal() as session:
        report = await evaluate_recall(
            session,
            user_id=UUID(args.user_id),
            kb_id=UUID(args.kb_id),
            questions=questions,
            top_k=args.top_k,
            embedder=build_embedder(),
        )

    print(f"Recall@{args.top_k}: {report.recall:.3f} ({report.hits}/{report.total})")
    return 0 if report.recall >= args.min_recall else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True, help="JSONL question file")
    parser.add_argument("--user-id", required=True, help="owner of the knowledge base")
    parser.add_argument("--kb-id", required=True, help="knowledge base to evaluate")
    parser.add_argument("--top-k", type=int, default=5, help="retrieval depth (default 5)")
    parser.add_argument(
        "--min-recall", type=float, default=0.0, help="exit non-zero below this recall"
    )
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
