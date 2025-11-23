#!/usr/bin/env python3
"""
lesson_learned.py

Record "lessons learned", append them to a log file, summarize the full log
into a PDF, and drop a ready-to-push marker file.

Paths used:
- Log file: /var/lib/dt-core/lesson_learned_full_11_23.txt
- PDF summary: /var/lib/dt-core/lesson_learn.pdf
- Ready marker: /tmp/files-will-get-deleted-1123/ready-to-push.txt
"""

import os
import sys
import datetime
from pathlib import Path

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
    """Append a lesson entry with timestamp to the lessons file."""
    LESSON_FILE.parent.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.datetime.now().isoformat(timespec="seconds")
    entry = f"\n--- LESSON {timestamp} ---\n{lesson_text.strip()}\n"
    with LESSON_FILE.open("a", encoding="utf-8") as f:
        f.write(entry)
    _stderr(f"Appended lesson to {LESSON_FILE}")


def read_full_lessons() -> str:
    """Read the entire lessons file, return as text."""
    if not LESSON_FILE.exists():
        _stderr(f"{LESSON_FILE} does not exist yet; returning empty text.")
        return ""
    return LESSON_FILE.read_text(encoding="utf-8")


def _fallback_summary(text: str, max_chars: int = 2000) -> str:
    """
    Very simple fallback summarizer used when AI is not available.
    It just truncates the text and wraps it with a header.
    """
    if not text.strip():
        return "No lessons have been recorded yet."
    trimmed = text.strip()
    if len(trimmed) > max_chars:
        trimmed = trimmed[:max_chars] + "\n\n[Summary truncated due to length.]"
    return "Lessons Learned (Fallback Summary):\n\n" + trimmed


def summarize_with_ai(text: str) -> str:
    """
    Summarize the lessons text using an AI model if possible.
    - Uses OpenAI if OPENAI_API_KEY and 'openai' library are available.
    - Falls back to a simple truncation summary otherwise.
    """
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
            model="gpt-4o-mini",  # adjust if needed
            messages=[
                {
                    "role": "system",
                    "content": (
                        "You are a concise assistant. Summarize the following "
                        "log of 'lessons learned' into a clear, readable summary "
                        "for a human to review later."
                    ),
                },
                {
                    "role": "user",
                    "content": text,
                },
            ],
            max_tokens=600,
            temperature=0.2,
        )
        summary = resp.choices[0].message.content or ""
        return summary.strip() or _fallback_summary(text)
    except Exception as e:  # noqa: BLE001
        _stderr(f"Error during AI summarization: {e!r}. Using fallback summary.")
        return _fallback_summary(text)


def write_pdf_summary(summary_text: str, pdf_path: Path) -> None:
    """
    Write the given summary text into a simple PDF.

    Requires: `pip install fpdf2`
    """
    try:
        from fpdf import FPDF  # type: ignore
    except ImportError:
        _stderr("fpdf library not installed. Cannot write PDF summary.")
        return

    class PDF(FPDF):
        pass

    pdf = PDF()
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_font("Arial", size=12)

    # Simple multi-line text output
    for line in summary_text.splitlines():
        pdf.multi_cell(0, 8, line)
    pdf.output(str(pdf_path))
    _stderr(f"Wrote PDF summary to {pdf_path}")


def write_ready_marker(path: Path) -> None:
    """Create the ready-to-push marker file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("ready\n", encoding="utf-8")
    _stderr(f"Wrote ready marker to {path}")


def collect_lesson_interactively() -> str:
    """
    Ask the user to input what they learned and return the text.

    This function can be skipped if another script wants to pass the lesson_text
    directly into append_lesson_to_file.
    """
    print("This is a LESSON LEARNED entry.")
    print("Please describe what you learned. Finish with Enter, then Ctrl+D (Linux/macOS) or Ctrl+Z, Enter (Windows).")
    print("----- START TYPING BELOW -----")

    try:
        # Read multi-line input from stdin
        lesson_text = sys.stdin.read()
    except KeyboardInterrupt:
        _stderr("User cancelled input.")
        return ""
    return lesson_text.strip()


# ========= MAIN FLOW =========

def run_lesson_flow(lesson_text: str | None = None) -> None:
    """
    Main flow:
    1. Get lesson text (interactive if not provided).
    2. Append to lessons file.
    3. Read full lessons file.
    4. Summarize with AI/fallback.
    5. Write summary to PDF.
    6. Write ready-to-push marker.
    """
    if lesson_text is None or not lesson_text.strip():
        lesson_text = collect_lesson_interactively()

    if not lesson_text:
        _stderr("No lesson text provided. Exiting without changes.")
        return

    append_lesson_to_file(lesson_text)
    full_text = read_full_lessons()
    summary = summarize_with_ai(full_text)
    write_pdf_summary(summary, PDF_SUMMARY_FILE)
    write_ready_marker(READY_MARKER)


if __name__ == "__main__":
    # When run directly: do the full lesson flow interactively.
    run_lesson_flow()
i
