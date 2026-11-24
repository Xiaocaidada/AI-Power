"""Pure text enhancement helpers for knowledge processing nodes."""

import hashlib
import re
import unicodedata
from collections import Counter

from app.services.knowledge.schema import (
    DedupeChunksConfig,
    FilterTextConfig,
    SummarizeChunksConfig,
)
from app.services.parsing import ParsedPage

LATIN_WORD = re.compile(r"[A-Za-z][A-Za-z0-9_+-]{2,}")
CJK_RUN = re.compile(r"[一-鿿]{2,}")
SENTENCE_SPLIT = re.compile(r"(?<=[。！？!?])\s*|(?<=[.])\s+|\n+")
CJK_STOPWORDS = {
    "我们",
    "你们",
    "他们",
    "这个",
    "那个",
    "这些",
    "那些",
    "以及",
    "或者",
    "并且",
    "因为",
    "所以",
    "但是",
    "如果",
    "可以",
    "需要",
    "进行",
    "一个",
    "没有",
    "通过",
    "使用",
    "相关",
    "其中",
    "对于",
    "由于",
    "然后",
    "已经",
    "还是",
    "就是",
    "不是",
}
EN_STOPWORDS = {
    "the",
    "and",
    "for",
    "with",
    "that",
    "this",
    "from",
    "are",
    "was",
    "were",
    "have",
    "has",
    "had",
    "not",
    "you",
    "your",
    "our",
    "their",
    "but",
    "can",
    "will",
    "would",
    "should",
    "into",
    "than",
    "then",
    "them",
    "these",
    "those",
    "about",
    "after",
    "before",
    "when",
    "where",
    "which",
}


def _norm(line: str) -> str:
    return " ".join(line.split()).strip()


def filter_pages(
    pages: list[ParsedPage], config: FilterTextConfig
) -> list[ParsedPage]:
    patterns: list[re.Pattern[str]] = []
    for raw in config.drop_patterns.splitlines():
        pattern = raw.strip()
        if not pattern:
            continue
        try:
            patterns.append(re.compile(pattern))
        except re.error as exc:
            raise ValueError(f"Invalid drop pattern: {exc}") from None

    boilerplate: set[str] = set()
    if config.drop_boilerplate and len(pages) >= 2:
        counts: Counter[str] = Counter()
        for page in pages:
            for line in {_norm(item) for item in page.text.splitlines() if _norm(item)}:
                counts[line] += 1
        threshold = max(2, int(len(pages) * 0.5 + 0.999))
        boilerplate = {line for line, count in counts.items() if count >= threshold}

    result: list[ParsedPage] = []
    for page in pages:
        seen: set[str] = set()
        kept: list[str] = []
        for line in page.text.splitlines():
            text = unicodedata.normalize("NFKC", line) if config.normalize_width else line
            normalized = _norm(text)
            if normalized:
                if config.drop_boilerplate and normalized in boilerplate:
                    continue
                if patterns and any(pattern.search(normalized) for pattern in patterns):
                    continue
                if 0 < len(normalized) < config.min_line_chars:
                    continue
                if config.dedupe_lines:
                    if normalized in seen:
                        continue
                    seen.add(normalized)
            kept.append(text)
        result.append(ParsedPage(page_no=page.page_no, text="\n".join(kept).strip()))
    return result


def extract_keywords(text: str, limit: int) -> list[str]:
    counts: Counter[str] = Counter()
    for word in LATIN_WORD.findall(text):
        lowered = word.casefold()
        if lowered not in EN_STOPWORDS:
            counts[lowered] += 1
    for run in CJK_RUN.findall(text):
        for size in (2, 3):
            for index in range(0, len(run) - size + 1):
                candidate = run[index : index + size]
                if candidate not in CJK_STOPWORDS:
                    counts[candidate] += 1
    ranked = sorted(
        counts.items(),
        key=lambda item: (-(item[1] * max(2, len(item[0]))), item[0]),
    )
    selected: list[str] = []
    for word, _count in ranked:
        if any(word in existing for existing in selected):
            continue
        selected.append(word)
        if len(selected) >= limit:
            break
    return selected


def summarize_text(text: str, config: SummarizeChunksConfig) -> str:
    sentences = [part.strip() for part in SENTENCE_SPLIT.split(text) if part.strip()]
    if not sentences:
        return ""
    if config.mode == "first_sentence":
        return sentences[0][: config.max_chars]
    frequencies: Counter[str] = Counter()
    for sentence in sentences:
        for word in LATIN_WORD.findall(sentence):
            frequencies[word.casefold()] += 1
        for run in CJK_RUN.findall(sentence):
            for index in range(0, len(run) - 1):
                frequencies[run[index : index + 2]] += 1
    ranked = sorted(
        enumerate(sentences),
        key=lambda item: (
            -sum(frequencies.get(word, 0) for word in LATIN_WORD.findall(item[1]))
            - sum(
                frequencies.get(run[index : index + 2], 0)
                for run in CJK_RUN.findall(item[1])
                for index in range(0, len(run) - 1)
            ),
            item[0],
        ),
    )
    chosen = sorted(index for index, _sentence in ranked[:3])
    summary = ""
    for index in chosen:
        candidate = f"{summary} {sentences[index]}".strip()
        if len(candidate) > config.max_chars:
            if not summary:
                summary = sentences[index][: config.max_chars]
            break
        summary = candidate
    return summary


def _trigrams(text: str) -> set[str]:
    normalized = re.sub(r"\s+", " ", text.casefold()).strip()
    if len(normalized) <= 3:
        return {normalized} if normalized else set()
    return {normalized[index : index + 3] for index in range(len(normalized) - 2)}


def dedupe_chunks(
    chunks: list[dict[str, object]], config: DedupeChunksConfig
) -> tuple[list[dict[str, object]], int]:
    kept: list[dict[str, object]] = []
    seen_hashes: set[str] = set()
    buckets: dict[int, list[tuple[int, set[str]]]] = {}
    removed = 0
    for chunk in chunks:
        text = str(chunk.get("text") or "")
        if not text.strip():
            removed += 1
            continue
        if len(text) < config.min_chars:
            kept.append(chunk)
            continue
        normalized = re.sub(r"\s+", " ", text.casefold()).strip()
        digest = hashlib.sha1(normalized.encode("utf-8")).hexdigest()
        if digest in seen_hashes:
            removed += 1
            continue
        trigrams = _trigrams(normalized)
        bucket = len(normalized) // 100
        duplicate = False
        for candidate_bucket in (bucket - 1, bucket):
            for _kept_index, candidate in buckets.get(candidate_bucket, []):
                if not trigrams or not candidate:
                    continue
                overlap = len(trigrams & candidate) / len(trigrams | candidate)
                if overlap >= config.threshold:
                    duplicate = True
                    break
            if duplicate:
                break
        if duplicate:
            removed += 1
            continue
        seen_hashes.add(digest)
        buckets.setdefault(bucket, []).append((len(kept), trigrams))
        kept.append(chunk)
    for index, chunk in enumerate(kept):
        chunk["chunk_index"] = index
    return kept, removed