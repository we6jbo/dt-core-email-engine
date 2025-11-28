#!/usr/bin/env python3
"""
lesson_learned.py

This module is safe to import from decision_engine.py.

RULES:
- append_lesson_to_file(text) → ONLY append the text and return immediately.
- NEVER ask for input.
- NEVER run PDF/summary/marker steps unless running as __main__.

Paths used:
- Log file: /var/lib/dt-core/lesson_learned_full_11_23.txt
- PDF summary: /var/lib/dt-core/lesson_learn.pdf
- Ready marker: /tmp/files-will-get-deleted-1123/ready-to-push.txt
"""

import os
import sys
import datetime
from pathlib import Path
from typing import Optional, Callable

# ========= CONSTANTS =========

LESSON_FILE = Path("/var/lib/dt-core/lesson_learned_full_11_23.txt")
PDF_SUMMARY_FILE = LESSON_FILE.parent / "lesson_learn.pdf"
READY_DIR = Path("/tmp/files-will-get-deleted-1123")
READY_MARKER = READY_DIR / "ready-to-push.txt"


# ========= HELPERS =========

def _stderr(msg: str) -> None:
    """Write a message to stderr with a timestamp."""
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    sys.stderr.write(f"[lesson_learned {now}] {msg}\n")
    sys.stderr.flush()


def append_lesson_to_file(lesson_text: str) -> None:
    """
    Append a lesson entry with timestamp to the lessons file.

    *** NEVER asks for input. NEVER writes PDFs. ***

    This is the ONLY function decision_engine.py calls.
    It MUST return immediately after writing the text.
    """
    text = (lesson_text or "").strip()
    if not text:
        _stderr("append_lesson_to_file: empty lesson_text; nothing written.")
        return

    LESSON_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    entry = f"\n--- LESSON {timestamp} ---\n{text}\n"

    with LESSON_FILE.open("a", encoding="utf-8") as f:
        f.write(entry)

    _stderr(f"Appended lesson to {LESSON_FILE}")
    return


def read_full_lessons() -> str:
    """Read the entire lessons file (used only for summary generation)."""
    if not LESSON_FILE.exists():
        _stderr(f"{LESSON_FILE} does not exist yet; returning empty text.")
        return ""
    return LESSON_FILE.read_text(encoding="utf-8")


def _fallback_summary(text: str, max_chars: int = 2000) -> str:
    """Simple fallback summarizer."""
    if not text.strip():
        return "No lessons have been recorded yet."
    trimmed = text.strip()
    if len(trimmed) > max_chars:
        trimmed = trimmed[:max_chars] + "\n\n[Summary truncated due to length.]"
    return "Lessons Learned (Fallback Summary):\n\n" + trimmed


def summarize_with_ai(text: str) -> str:
    """Attempt OpenAI summarization; fallback if unavailable."""
    if not text.strip():
        return "No lessons have been recorded yet."

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        _stderr("OPENAI_API_KEY not set. Using fallback summary.")
        return _fallback_summary(text)

    try:
        from openai import OpenAI  # type: ignore
    except ImportError:
        _stderr("openai library not installed. Using fallback summary.")
        return _fallback_summary(text)

    try:
        client = OpenAI(api_key=api_key)
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Summarize the following lessons clearly and concisely."
                    ),
                },
                {"role": "user", "content": text},
            ],
            max_tokens=600,
            temperature=0.2,
        )
        summary = resp.choices[0].message.content or ""
        return summary.strip() or _fallback_summary(text)
    except Exception as e:
        _stderr(f"Error during AI summarization: {e!r}. Using fallback.")
        return _fallback_summary(text)


def write_pdf_summary(summary_text: str, pdf_path: Path) -> None:
    """
    Write summary to a PDF. Only used during __main__ invocation.
    """
    try:
        from fpdf import FPDF  # type: ignore
    except ImportError:
        _stderr("fpdf library not installed. Cannot write PDF.")
        return

    class PDF(FPDF):
        pass

    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    for line in summary_text.splitlines():
        pdf.multi_cell(0, 8, line)

    pdf.output(str(pdf_path))
    _stderr(f"Wrote PDF summary to {pdf_path}")


def write_ready_marker(path: Path) -> None:
    """Create the ready-to-push marker file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ready\n", encoding="utf-8")
    _stderr(f"Wrote ready marker to {path}")


# ========= MAIN FLOW =========

def run_lesson_flow(get_lesson: Callable[[], str]) -> None:
    """
    Full processing pipeline, ONLY used when running this script directly
    or when another script explicitly passes a function.

    get_lesson: a function that returns the lesson_text (no user prompts here).

    Steps:
    - get lesson text
    - append
    - summarize
    - PDF
    - ready flag
    """
    lesson_text = (get_lesson() or "").strip()
    if not lesson_text:
        _stderr("No lesson provided by get_lesson(); exiting.")
        return

    append_lesson_to_file(lesson_text)
    full_text = read_full_lessons()
    summary = summarize_with_ai(full_text)
    write_pdf_summary(summary, PDF_SUMMARY_FILE)
    write_ready_marker(READY_MARKER)


if __name__ == "__main__":
    # Example: no user input, just a hard-coded lesson text.
    def _example_lesson() -> str:
        return "lesson_learned.py this is what I learn."

    run_lesson_flow(_example_lesson)

