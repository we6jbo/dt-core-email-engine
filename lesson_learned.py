#!/usr/bin/env python3

import sys
from pathlib import Path

from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

LESSON_FILE = Path("/var/lib/dt-core/lesson_learned_full_11_23.txt")
SUMMARY_PDF_FILE = Path("/var/lib/dt-core/lesson_learnedA.pdf")
READY_MARKER = Path("/tmp/files-will-get-deleted-1123/ready-to-push.txt")


def append_argument_to_lesson_file(text: str) -> None:
    LESSON_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LESSON_FILE.open("a", encoding="utf-8") as f:
        f.write(text + "\n")


def read_lesson_file() -> str:
    if not LESSON_FILE.exists():
        return ""
    return LESSON_FILE.read_text(encoding="utf-8")


def write_summary_pdf(content: str) -> None:
    SUMMARY_PDF_FILE.parent.mkdir(parents=True, exist_ok=True)
    c = canvas.Canvas(str(SUMMARY_PDF_FILE), pagesize=LETTER)
    width, height = LETTER

    text_obj = c.beginText()
    text_obj.setTextOrigin(72, height - 72)  # 1 inch margin

    for line in content.splitlines():
        text_obj.textLine(line)

    c.drawText(text_obj)
    c.showPage()
    c.save()


def create_ready_marker() -> None:
    READY_MARKER.parent.mkdir(parents=True, exist_ok=True)
    READY_MARKER.touch()


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: lesson_learned_cli.py This is my argument")
        sys.exit(1)

    argument_text = " ".join(sys.argv[1:])

    # 1) Append argument to lesson file
    append_argument_to_lesson_file(argument_text)

    # 2) Read full lesson file and write it into a PDF
    content = read_lesson_file()
    write_summary_pdf(content)

    # 3) Create ready marker (blank file)
    create_ready_marker()


if __name__ == "__main__":
    main()

