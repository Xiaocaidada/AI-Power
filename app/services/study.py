import json
import logging
import re
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Conversation, KnowledgeBase, StudyAttempt, StudySession
from app.providers.base import ChatMessage, LLMProvider
from app.services.model_stream import ModelCompletion
from app.services.usage_ledger import SOURCE_STUDY

logger = logging.getLogger(__name__)

STUDY_LEVELS = ("beginner", "intermediate", "advanced")
STUDY_MODES = ("explain", "guided", "practice", "quiz", "review")
STUDY_STATUSES = ("active", "completed", "archived")
QUESTION_TYPES = ("single_choice", "multiple_choice", "true_false", "short_answer")
MAX_QUESTIONS = 10
DEFAULT_QUESTION_COUNT = 5


class StudyError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def _normalize_level(value: str) -> str:
    level = (value or "").strip().lower()
    if level not in STUDY_LEVELS:
        raise StudyError("invalid_level", "Unsupported study level")
    return level


def _normalize_mode(value: str) -> str:
    mode = (value or "").strip().lower()
    if mode not in STUDY_MODES:
        raise StudyError("invalid_study_mode", "Unsupported study mode")
    return mode


async def _validate_conversation(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    conversation_id: UUID | None,
) -> Conversation | None:
    if conversation_id is None:
        return None
    conversation = (
        await session.execute(
            select(Conversation).where(
                Conversation.id == conversation_id,
                Conversation.workspace_id == workspace_id,
                Conversation.user_id == user_id,
                Conversation.archived_at.is_(None),
            )
        )
    ).scalar_one_or_none()
    if conversation is None:
        raise StudyError("conversation_not_found", "Conversation not found")
    return conversation


async def _validate_kb_ids(
    session: AsyncSession, workspace_id: UUID, kb_ids: list[UUID]
) -> list[str]:
    if not kb_ids:
        return []
    rows = list(
        (
            await session.execute(
                select(KnowledgeBase.id).where(
                    KnowledgeBase.id.in_(kb_ids),
                    KnowledgeBase.workspace_id == workspace_id,
                    KnowledgeBase.deleted_at.is_(None),
                )
            )
        ).scalars()
    )
    if len(rows) != len(set(kb_ids)):
        raise StudyError("knowledge_base_not_found", "Knowledge base not found")
    return [str(item) for item in dict.fromkeys(kb_ids)]


async def get_session(
    session: AsyncSession, session_id: UUID, workspace_id: UUID, user_id: UUID
) -> StudySession:
    study = (
        await session.execute(
            select(StudySession).where(
                StudySession.id == session_id,
                StudySession.workspace_id == workspace_id,
                StudySession.user_id == user_id,
            )
        )
    ).scalar_one_or_none()
    if study is None:
        raise StudyError("study_session_not_found", "Study session not found")
    return study


async def list_sessions(
    session: AsyncSession,
    workspace_id: UUID,
    user_id: UUID,
    *,
    conversation_id: UUID | None = None,
    status: str | None = None,
) -> list[StudySession]:
    conditions = [
        StudySession.workspace_id == workspace_id,
        StudySession.user_id == user_id,
    ]
    if conversation_id is not None:
        conditions.append(StudySession.conversation_id == conversation_id)
    if status is not None:
        if status not in STUDY_STATUSES:
            raise StudyError("invalid_status", "Unsupported study status")
        conditions.append(StudySession.status == status)
    return list(
        (
            await session.execute(
                select(StudySession)
                .where(*conditions)
                .order_by(StudySession.updated_at.desc(), StudySession.id.desc())
                .limit(100)
            )
        ).scalars()
    )


async def create_session(
    session: AsyncSession,
    *,
    workspace_id: UUID,
    user_id: UUID,
    topic: str,
    conversation_id: UUID | None,
    level: str,
    mode: str,
    goals: str,
    kb_ids: list[UUID],
) -> StudySession:
    text = (topic or "").strip()
    if text == "":
        raise StudyError("topic_required", "Study topic is required")
    await _validate_conversation(
        session,
        workspace_id=workspace_id,
        user_id=user_id,
        conversation_id=conversation_id,
    )
    study = StudySession(
        workspace_id=workspace_id,
        user_id=user_id,
        conversation_id=conversation_id,
        topic=text[:200],
        level=_normalize_level(level),
        mode=_normalize_mode(mode),
        goals=(goals or "").strip()[:2000],
        kb_ids=await _validate_kb_ids(session, workspace_id, kb_ids),
        status="active",
        mastery={},
    )
    session.add(study)
    await session.flush()
    return study


async def update_session(
    session: AsyncSession,
    study: StudySession,
    *,
    topic: str | None = None,
    level: str | None = None,
    mode: str | None = None,
    goals: str | None = None,
    kb_ids: list[UUID] | None = None,
    status: str | None = None,
) -> StudySession:
    if topic is not None:
        text = topic.strip()
        if text == "":
            raise StudyError("topic_required", "Study topic is required")
        study.topic = text[:200]
    if level is not None:
        study.level = _normalize_level(level)
    if mode is not None:
        study.mode = _normalize_mode(mode)
    if goals is not None:
        study.goals = goals.strip()[:2000]
    if kb_ids is not None:
        study.kb_ids = await _validate_kb_ids(session, study.workspace_id, kb_ids)
    if status is not None:
        if status not in STUDY_STATUSES:
            raise StudyError("invalid_status", "Unsupported study status")
        study.status = status
    await session.flush()
    return study


async def list_attempts(session: AsyncSession, study: StudySession) -> list[StudyAttempt]:
    return list(
        (
            await session.execute(
                select(StudyAttempt)
                .where(StudyAttempt.session_id == study.id)
                .order_by(StudyAttempt.created_at, StudyAttempt.id)
            )
        ).scalars()
    )


def _quiz_prompt(study: StudySession, count: int, types: list[str]) -> str:
    allowed = ", ".join(types)
    weak = (study.mastery or {}).get("weak_points", [])
    weak_text = "; ".join(str(item) for item in weak[:5]) or "none"
    return "\n".join(
        [
            "Generate a study quiz as strict JSON only. Do not use Markdown fences.",
            "Schema:",
            '{"questions":[{"type":"single_choice|multiple_choice|true_false|short_answer",'
            '"prompt":"...","options":[{"id":"A","text":"..."}],'
            '"answer":["A"],"explanation":"..."}]}',
            f"Topic: {study.topic}",
            f"Level: {study.level}",
            f"Study mode: {study.mode}",
            f"Goals: {study.goals or 'none'}",
            f"Weak points: {weak_text}",
            f"Allowed types: {allowed}",
            f"Question count: {count}",
            "Rules: single_choice has exactly one answer; multiple_choice has one or more; "
            "true_false uses options [{id:'true'},{id:'false'}] and answer ['true'] or "
            "['false']; short_answer has no options and answer is a list of acceptable "
            "short strings. Every question must include an explanation. Use Chinese unless "
            "the topic clearly requires another language.",
        ]
    )


def _extract_json(content: str) -> object:
    text = (content or "").strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end <= start:
        raise StudyError("quiz_generation_failed", "Quiz model returned no JSON")
    try:
        return json.loads(text[start : end + 1])
    except ValueError:
        raise StudyError("quiz_generation_failed", "Quiz model returned invalid JSON") from None


def _normalize_options(raw: object, *, true_false: bool = False) -> list[dict[str, str]]:
    if true_false:
        return [{"id": "true", "text": "正确"}, {"id": "false", "text": "错误"}]
    if not isinstance(raw, list):
        return []
    options: list[dict[str, str]] = []
    for index, item in enumerate(raw):
        if isinstance(item, dict):
            option_id = str(item.get("id") or chr(65 + index)).strip()
            text = str(item.get("text") or "").strip()
        else:
            option_id = chr(65 + index)
            text = str(item).strip()
        if text:
            options.append({"id": option_id[:10], "text": text[:500]})
        if len(options) >= 8:
            break
    return options


def _normalize_answer(raw: object, *, short_answer: bool) -> list[str]:
    if isinstance(raw, list):
        values = [str(item).strip() for item in raw]
    elif raw is None:
        values = []
    else:
        values = [str(raw).strip()]
    values = [item for item in values if item]
    if short_answer:
        return [item.casefold() for item in values][:10]
    return [item[:10] for item in values][:8]


def _normalize_question(raw: object, index: int) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    kind = str(raw.get("type") or "").strip().lower()
    if kind in {"single", "single_choice", "choice"}:
        kind = "single_choice"
    elif kind in {"multiple", "multiple_choice", "multi"}:
        kind = "multiple_choice"
    elif kind in {"true_false", "boolean", "judge"}:
        kind = "true_false"
    elif kind in {"short_answer", "short", "fill", "fill_blank"}:
        kind = "short_answer"
    if kind not in QUESTION_TYPES:
        return None
    prompt = str(raw.get("prompt") or raw.get("question") or "").strip()
    if prompt == "":
        return None
    short_answer = kind == "short_answer"
    options = _normalize_options(raw.get("options"), true_false=kind == "true_false")
    if not short_answer and len(options) < 2:
        return None
    answer = _normalize_answer(raw.get("answer"), short_answer=short_answer)
    if not answer:
        return None
    option_ids = {item["id"].casefold() for item in options}
    if not short_answer:
        if any(item.casefold() not in option_ids for item in answer):
            return None
        if kind == "single_choice" and len(answer) != 1:
            return None
        if kind == "true_false" and len(answer) != 1:
            return None
    return {
        "id": f"q{index}",
        "type": kind,
        "prompt": prompt[:2000],
        "options": options,
        "answer": answer,
        "explanation": str(raw.get("explanation") or "")[:2000],
    }


def parse_questions(content: str, count: int) -> list[dict[str, Any]]:
    payload = _extract_json(content)
    rows = payload.get("questions") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise StudyError("quiz_generation_failed", "Quiz JSON has no questions")
    questions: list[dict[str, Any]] = []
    for index, row in enumerate(rows, start=1):
        normalized = _normalize_question(row, index)
        if normalized is not None:
            questions.append(normalized)
        if len(questions) >= count:
            break
    if not questions:
        raise StudyError("quiz_generation_failed", "Quiz model returned no valid questions")
    return questions


async def generate_quiz(
    session: AsyncSession,
    study: StudySession,
    *,
    provider: LLMProvider,
    model: str,
    count: int = DEFAULT_QUESTION_COUNT,
    types: list[str] | None = None,
) -> list[StudyAttempt]:
    allowed = [item for item in (types or list(QUESTION_TYPES)) if item in QUESTION_TYPES]
    if not allowed:
        raise StudyError("invalid_question_type", "No supported question type selected")
    count = max(1, min(int(count), MAX_QUESTIONS))
    completion = ModelCompletion(
        provider=provider,
        model=model,
        messages=[
            ChatMessage(
                role="user",
                content=_quiz_prompt(study, count, allowed),
            )
        ],
        opts={"temperature": 0.3, "max_tokens": 2500},
        workspace_id=study.workspace_id,
        user_id=study.user_id,
        source=SOURCE_STUDY,
    )
    metrics = await completion.run()
    if metrics.status != "completed":
        raise StudyError(metrics.error_code or "quiz_generation_failed", "Quiz generation failed")
    questions = parse_questions(metrics.content, count)
    attempts = [
        StudyAttempt(
            session_id=study.id,
            question=question,
            answer="",
            score=None,
            feedback="",
            status="pending",
        )
        for question in questions
    ]
    session.add_all(attempts)
    await session.flush()
    return attempts


def _normalize_submission(question: dict[str, Any], answer: Any) -> list[str]:
    if isinstance(answer, list):
        values = [str(item).strip() for item in answer]
    else:
        raw = str(answer or "").strip()
        if question.get("type") in {"multiple_choice", "short_answer"}:
            values = [item.strip() for item in re.split(r"[,，;；]", raw)]
        else:
            values = [raw]
    values = [item for item in values if item]
    if question.get("type") == "short_answer":
        return [item.casefold() for item in values]
    return [item[:10].casefold() for item in values]


def grade_answer(question: dict[str, Any], answer: Any) -> tuple[float, str]:
    submitted = _normalize_submission(question, answer)
    expected_raw = [str(item) for item in question.get("answer", [])]
    expected = (
        [item.casefold() for item in expected_raw]
        if question.get("type") != "short_answer"
        else expected_raw
    )
    kind = str(question.get("type") or "")
    if kind == "short_answer":
        correct = any(item in expected for item in submitted)
    elif kind == "multiple_choice":
        correct = set(submitted) == set(expected)
    else:
        correct = len(submitted) == 1 and submitted[0] in expected
    explanation = str(question.get("explanation") or "").strip()
    if correct:
        feedback = "回答正确。" + (f" {explanation}" if explanation else "")
        return 1.0, feedback[:2000]
    shown = ", ".join(expected_raw)
    feedback = f"回答不正确。正确答案：{shown}。"
    if explanation:
        feedback = f"{feedback} {explanation}"
    return 0.0, feedback[:2000]


async def grade_attempt(
    session: AsyncSession, study: StudySession, attempt: StudyAttempt, answer: Any
) -> StudyAttempt:
    if attempt.session_id != study.id:
        raise StudyError("attempt_not_found", "Study attempt not found")
    if attempt.status != "pending":
        raise StudyError("attempt_already_graded", "Attempt is already graded")
    score, feedback = grade_answer(attempt.question, answer)
    attempt.answer = answer if isinstance(answer, str) else json.dumps(answer, ensure_ascii=False)
    attempt.score = score
    attempt.feedback = feedback
    attempt.status = "graded"
    attempt.graded_at = datetime.now(UTC)
    await session.flush()
    await refresh_mastery(session, study)
    return attempt


async def refresh_mastery(session: AsyncSession, study: StudySession) -> dict[str, Any]:
    attempts = await list_attempts(session, study)
    graded = [item for item in attempts if item.score is not None]
    answered = len(graded)
    correct = sum(1 for item in graded if (item.score or 0) >= 0.999)
    accuracy = round(correct / answered, 4) if answered else 0.0
    by_type: dict[str, dict[str, int]] = {}
    weak_points: list[str] = []
    for item in graded:
        kind = str(item.question.get("type") or "unknown")
        bucket = by_type.setdefault(kind, {"answered": 0, "correct": 0})
        bucket["answered"] += 1
        if (item.score or 0) >= 0.999:
            bucket["correct"] += 1
        elif len(weak_points) < 5:
            weak_points.append(str(item.question.get("prompt") or "")[:120])
    if answered == 0:
        suggestions = ["先生成一组练习题，系统会根据答题结果给出掌握度建议。"]
    elif accuracy < 0.6:
        suggestions = [
            "正确率偏低：先逐题阅读错题解析，再切换到讲解或引导模式复习基础概念。",
            "针对薄弱点生成一组更简单的练习，完成后再次查看掌握度。",
        ]
    elif accuracy < 0.85:
        suggestions = [
            "整体掌握良好：针对错题对应的知识点再做一组练习。",
            "尝试用自己的话总结关键概念，然后进入复习模式检查遗漏。",
        ]
    else:
        suggestions = [
            "掌握良好：可以提高难度或切换到复习模式做间隔复习。",
            "尝试解释为什么答案成立，而不只是记住结论。",
        ]
    study.mastery = {
        "answered": answered,
        "correct": correct,
        "accuracy": accuracy,
        "by_type": by_type,
        "weak_points": weak_points,
        "suggestions": suggestions,
        "updated_at": datetime.now(UTC).isoformat(),
    }
    await session.flush()
    return study.mastery


def public_attempt(attempt: StudyAttempt) -> dict[str, Any]:
    question = attempt.question or {}
    payload: dict[str, Any] = {
        "id": attempt.id,
        "type": question.get("type", "short_answer"),
        "prompt": question.get("prompt", ""),
        "options": question.get("options", []),
        "status": attempt.status,
        "answer": attempt.answer,
        "score": attempt.score,
        "feedback": attempt.feedback,
        "created_at": attempt.created_at,
        "graded_at": attempt.graded_at,
    }
    if attempt.status == "graded":
        payload["correct_answer"] = question.get("answer", [])
        payload["explanation"] = question.get("explanation", "")
    return payload


def build_study_system_prompt(study: StudySession, base_prompt: str | None) -> str:
    mastery = study.mastery or {}
    lines = [
        "You are a patient study tutor.",
        f"Topic: {study.topic}",
        f"Level: {study.level}",
        f"Study mode: {study.mode}",
        f"Goals: {study.goals or 'not specified'}",
        f"Answered: {mastery.get('answered', 0)}; accuracy: {mastery.get('accuracy', 0)}",
    ]
    weak = mastery.get("weak_points") or []
    if weak:
        lines.append("Weak points: " + "; ".join(str(item) for item in weak[:5]))
    lines.extend(
        [
            "Adapt explanations to the level. In quiz mode ask one question at a time and "
            "do not reveal the answer before the learner attempts it. In guided mode use "
            "small steps and check understanding. In review mode focus on weak points and "
            "spaced review. Never invent citations.",
        ]
    )
    if base_prompt:
        lines.append("")
        lines.append(base_prompt)
    return "\n".join(lines)
