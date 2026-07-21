#!/usr/bin/env python3
"""Approved automatic answers for dt-core."""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Optional

CONFIG_PATH = Path("/var/lib/dt-core/known_answers.json")
QUEUE_DB = Path("/var/lib/baypark-decision-queue/questions.sqlite3")

# Deliberately conservative. Only very close wording is answered automatically.
FUZZY_THRESHOLD = 0.93

# These subjects should always receive human review.
HUMAN_REVIEW_TERMS = {
    "password",
    "credential",
    "api key",
    "token",
    "private key",
    "delete",
    "remove files",
    "format drive",
    "medical",
    "diagnosis",
    "legal advice",
    "financial advice",
}


@dataclass(frozen=True)
class KnownAnswer:
    answer_id: str
    answer: str
    confidence: float
    matched_question: str


def normalize_question(value: str) -> str:
    value = value.casefold()
    value = value.replace("’", "'")
    value = re.sub(r"[^a-z0-9\s']", " ", value)
    value = value.replace("'", "")
    value = re.sub(r"\s+", " ", value)
    return value.strip()


def load_entries() -> list[dict]:
    if not CONFIG_PATH.exists():
        return []

    data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    entries = data.get("answers", [])

    if not isinstance(entries, list):
        raise ValueError("known_answers.json: answers must be a list")

    return [entry for entry in entries if isinstance(entry, dict)]


def requires_human_review(question: str) -> bool:
    normalized = normalize_question(question)
    return any(term in normalized for term in HUMAN_REVIEW_TERMS)


def find_known_answer(question: str) -> Optional[KnownAnswer]:
    normalized = normalize_question(question)

    if not normalized:
        return KnownAnswer(
            answer_id="missing-question-body",
            answer=(
                "I received the request, but no question text was found. "
                "Please resend the request with the question in the message body."
            ),
            confidence=1.0,
            matched_question="",
        )

    if requires_human_review(normalized):
        return None

    best: Optional[KnownAnswer] = None

    for entry in load_entries():
        if not entry.get("enabled", True):
            continue

        answer = str(entry.get("answer", "")).strip()
        if not answer:
            continue

        answer_id = str(entry.get("id", "known-answer"))
        questions = entry.get("questions", [])

        if not isinstance(questions, list):
            continue

        for candidate in questions:
            candidate_normalized = normalize_question(str(candidate))

            if not candidate_normalized:
                continue

            if normalized == candidate_normalized:
                return KnownAnswer(
                    answer_id=answer_id,
                    answer=answer,
                    confidence=1.0,
                    matched_question=str(candidate),
                )

            score = SequenceMatcher(
                None,
                normalized,
                candidate_normalized,
            ).ratio()

            if score >= FUZZY_THRESHOLD and (
                best is None or score > best.confidence
            ):
                best = KnownAnswer(
                    answer_id=answer_id,
                    answer=answer,
                    confidence=score,
                    matched_question=str(candidate),
                )

    return best


def answer_existing_pending_questions() -> list[tuple[int, KnownAnswer]]:
    """Mark existing known pending questions as answered."""

    if not QUEUE_DB.exists():
        return []

    changed: list[tuple[int, KnownAnswer]] = []

    with sqlite3.connect(str(QUEUE_DB), timeout=10) as connection:
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout=10000")

        rows = connection.execute(
            """
            SELECT id, question
            FROM questions
            WHERE status = 'pending'
            ORDER BY id ASC
            """
        ).fetchall()

        for row in rows:
            match = find_known_answer(row["question"] or "")

            if match is None:
                continue

            connection.execute(
                """
                UPDATE questions
                SET status = 'answered',
                    answer = ?,
                    answered_at = datetime('now')
                WHERE id = ?
                  AND status = 'pending'
                """,
                (match.answer, int(row["id"])),
            )

            changed.append((int(row["id"]), match))

        connection.commit()

    return changed
