import json
from pathlib import Path

import pytest

DATASET_PATH = Path(__file__).resolve().parents[1] / "eval" / "dataset.json"
QUESTIONS_PATH = DATASET_PATH.with_name("questions.jsonl")


def _load():
    from app.services.evaluation import load_eval_dataset

    return load_eval_dataset(DATASET_PATH)


def test_dataset_has_twenty_documents_and_fifty_questions():
    documents, questions = _load()

    assert len(documents) == 20
    assert len(questions) == 50
    assert len({document.filename for document in documents}) == 20
    assert len({question.question for question in questions}) == 50


def test_every_document_is_referenced_and_every_reference_is_known():
    from app.services.evaluation import document_id_for

    documents, questions = _load()
    known = {document_id_for(document.filename) for document in documents}
    referenced = {
        document_id for question in questions for document_id in question.relevant_document_ids
    }

    assert referenced == known


def test_questions_are_non_empty_and_documents_have_text():
    documents, questions = _load()

    assert all(question.question.strip() for question in questions)
    assert all(len(document.text) >= 80 for document in documents)


def test_committed_questions_file_matches_dataset():
    from app.services.evaluation import render_questions_jsonl

    _documents, questions = _load()

    assert QUESTIONS_PATH.read_text(encoding="utf-8") == render_questions_jsonl(questions)


def test_loader_rejects_unknown_document_reference(tmp_path):
    from app.services.evaluation import load_eval_dataset

    broken = tmp_path / "broken.json"
    broken.write_text(
        json.dumps(
            {
                "documents": [{"filename": "known.md", "text": "x" * 100}],
                "questions": [{"question": "q", "relevant_filenames": ["missing.md"]}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="unknown document"):
        load_eval_dataset(broken)


def test_loader_rejects_duplicate_document_filenames(tmp_path):
    from app.services.evaluation import load_eval_dataset

    duplicated = tmp_path / "duplicated-docs.json"
    duplicated.write_text(
        json.dumps(
            {
                "documents": [
                    {"filename": "same.md", "text": "x" * 100},
                    {"filename": "same.md", "text": "y" * 100},
                ],
                "questions": [{"question": "q", "relevant_filenames": ["same.md"]}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate document filename"):
        load_eval_dataset(duplicated)


def test_loader_rejects_empty_question(tmp_path):
    from app.services.evaluation import load_eval_dataset

    empty = tmp_path / "empty-question.json"
    empty.write_text(
        json.dumps(
            {
                "documents": [{"filename": "known.md", "text": "x" * 100}],
                "questions": [{"question": "   ", "relevant_filenames": ["known.md"]}],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="empty question"):
        load_eval_dataset(empty)


def test_loader_rejects_duplicate_questions(tmp_path):
    from app.services.evaluation import load_eval_dataset

    duplicated = tmp_path / "duplicated.json"
    duplicated.write_text(
        json.dumps(
            {
                "documents": [{"filename": "known.md", "text": "x" * 100}],
                "questions": [
                    {"question": "same?", "relevant_filenames": ["known.md"]},
                    {"question": "same?", "relevant_filenames": ["known.md"]},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="duplicate question"):
        load_eval_dataset(duplicated)
