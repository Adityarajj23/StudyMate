"""Run this script once to generate a test syllabus PDF.

Usage: python data/create_test_pdf.py
Requires: pip install pymupdf (already in requirements.txt)
"""

import fitz
from pathlib import Path

SYLLABUS_MD = Path(__file__).parent / "test_syllabus_ds.md"
OUTPUT_PDF = Path(__file__).parent / "test_syllabus_data_structures.pdf"


def main():
    text = SYLLABUS_MD.read_text(encoding="utf-8")
    doc = fitz.open()

    lines = text.split("\n")
    page = doc.new_page(width=595, height=842)  # A4
    y = 50
    margin_left = 50
    max_width = 495

    fontsize_h1 = 16
    fontsize_h2 = 13
    fontsize_h3 = 11
    fontsize_body = 9.5

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped == "---":
            y += 8
            continue

        if stripped.startswith("# "):
            fs, text_content = fontsize_h1, stripped[2:]
        elif stripped.startswith("## "):
            fs, text_content = fontsize_h2, stripped[3:]
            y += 6
        elif stripped.startswith("### "):
            fs, text_content = fontsize_h3, stripped[4:]
            y += 4
        elif stripped.startswith("**") and stripped.endswith("**"):
            fs, text_content = fontsize_body, stripped[2:-2]
        elif stripped.startswith("- "):
            fs, text_content = fontsize_body, "  " + stripped
        elif stripped.startswith("| "):
            fs, text_content = fontsize_body - 1, stripped
        else:
            fs, text_content = fontsize_body, stripped

        line_height = fs + 4

        if y + line_height > 790:
            page = doc.new_page(width=595, height=842)
            y = 50

        page.insert_text(
            (margin_left, y),
            text_content,
            fontsize=fs,
            fontname="helv",
        )
        y += line_height

    doc.save(str(OUTPUT_PDF))
    doc.close()
    print(f"Created: {OUTPUT_PDF} ({OUTPUT_PDF.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
