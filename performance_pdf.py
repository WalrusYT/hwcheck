"""Builds a simple one-page performance report PDF for a student, to send to parents."""

from datetime import datetime, timezone
from pathlib import Path

import pymupdf as fitz

PAGE_WIDTH, PAGE_HEIGHT = fitz.paper_size("a4")
MARGIN = 50

FONT_DIR = Path(__file__).parent / "static" / "fonts"
FONT_REGULAR = "notosans"
FONT_BOLD = "notosans-bold"

LOGO_PATH = Path(__file__).parent / "static" / "logo" / "logo_report.png"
LOGO_HEIGHT = 34


def _new_page(doc):
    """Create a page with our Cyrillic-capable font registered as a resource
    (Base14 'helv' has no Cyrillic glyphs, which rendered Russian text as dots)."""
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    page.insert_font(fontname=FONT_REGULAR, fontfile=str(FONT_DIR / "NotoSans-Regular.ttf"))
    page.insert_font(fontname=FONT_BOLD, fontfile=str(FONT_DIR / "NotoSans-Bold.ttf"))
    return page


def build_performance_pdf(student_name, average_letter, average_gpa, history, narrative,
                          missed=(), handed_in=0, due=0):
    """history: list of {"title": str, "submitted_at": str, "grade": str}, most recent first;
    missed: list of {"title": str, "set_at": str} not handed in. Returns PDF bytes.
    """
    doc = fitz.open()
    page = _new_page(doc)
    y = MARGIN

    logo_pix = fitz.Pixmap(str(LOGO_PATH))
    logo_w = LOGO_HEIGHT * logo_pix.width / logo_pix.height
    page.insert_image(fitz.Rect(MARGIN, y, MARGIN + logo_w, y + LOGO_HEIGHT), filename=str(LOGO_PATH))
    y += LOGO_HEIGHT + 24

    page.insert_text((MARGIN, y), student_name, fontsize=14, fontname=FONT_BOLD)
    y += 18
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    page.insert_text((MARGIN, y), f"Generated {generated}", fontsize=9, fontname=FONT_REGULAR, color=(0.4, 0.4, 0.4))
    y += 30

    page.insert_text((MARGIN, y), "Average grade:", fontsize=12, fontname=FONT_BOLD)
    avg_text = f"{average_letter} ({average_gpa}/4.0)" if average_letter else "No graded homework yet"
    page.insert_text((MARGIN + 130, y), avg_text, fontsize=12, fontname=FONT_REGULAR)
    y += 20
    if due:
        page.insert_text((MARGIN, y), "Handed in:", fontsize=12, fontname=FONT_BOLD)
        page.insert_text((MARGIN + 130, y), f"{handed_in} of {due} homework assignments set",
                         fontsize=12, fontname=FONT_REGULAR)
        y += 20
    y += 10

    if narrative:
        # insert_textbox writes nothing at all when the text doesn't fit: grow the box
        for height in (90, 140, 200, 280):
            rect = fitz.Rect(MARGIN, y, PAGE_WIDTH - MARGIN, y + height)
            if page.insert_textbox(rect, narrative, fontsize=10.5, fontname=FONT_REGULAR, lineheight=1.4) >= 0:
                break
        y += height + 10

    y += 10
    page.insert_text((MARGIN, y), "Grade history", fontsize=13, fontname=FONT_BOLD)
    y += 10
    page.draw_line((MARGIN, y), (PAGE_WIDTH - MARGIN, y), color=(0.7, 0.7, 0.7))
    y += 18

    col_title_x = MARGIN
    col_date_x = PAGE_WIDTH - MARGIN - 180
    col_grade_x = PAGE_WIDTH - MARGIN - 60

    page.insert_text((col_title_x, y), "Homework", fontsize=9, fontname=FONT_REGULAR, color=(0.4, 0.4, 0.4))
    page.insert_text((col_date_x, y), "Date", fontsize=9, fontname=FONT_REGULAR, color=(0.4, 0.4, 0.4))
    page.insert_text((col_grade_x, y), "Grade", fontsize=9, fontname=FONT_REGULAR, color=(0.4, 0.4, 0.4))
    y += 14
    page.draw_line((MARGIN, y), (PAGE_WIDTH - MARGIN, y), color=(0.85, 0.85, 0.85))
    y += 14

    for item in history:
        if y > PAGE_HEIGHT - MARGIN:
            page = _new_page(doc)
            y = MARGIN

        title = item["title"]
        if len(title) > 45:
            title = title[:42] + "..."
        page.insert_text((col_title_x, y), title, fontsize=10, fontname=FONT_REGULAR)
        date_str = (item.get("submitted_at") or "")[:10]
        page.insert_text((col_date_x, y), date_str, fontsize=10, fontname=FONT_REGULAR)
        page.insert_text((col_grade_x, y), item["grade"], fontsize=10, fontname=FONT_BOLD)
        y += 18

    if not history:
        page.insert_text((MARGIN, y), "No graded homework yet.", fontsize=10, fontname=FONT_REGULAR, color=(0.5, 0.5, 0.5))
        y += 18

    if missed:
        if y > PAGE_HEIGHT - MARGIN - 80:
            page = _new_page(doc)
            y = MARGIN
        y += 20
        page.insert_text((MARGIN, y), "Not handed in", fontsize=13, fontname=FONT_BOLD)
        y += 10
        page.draw_line((MARGIN, y), (PAGE_WIDTH - MARGIN, y), color=(0.7, 0.7, 0.7))
        y += 18
        page.insert_text((col_title_x, y), "Homework", fontsize=9, fontname=FONT_REGULAR, color=(0.4, 0.4, 0.4))
        page.insert_text((col_date_x, y), "Set on", fontsize=9, fontname=FONT_REGULAR, color=(0.4, 0.4, 0.4))
        y += 14
        page.draw_line((MARGIN, y), (PAGE_WIDTH - MARGIN, y), color=(0.85, 0.85, 0.85))
        y += 14
        for item in missed:
            if y > PAGE_HEIGHT - MARGIN:
                page = _new_page(doc)
                y = MARGIN
            title = item["title"] if len(item["title"]) <= 45 else item["title"][:42] + "..."
            page.insert_text((col_title_x, y), title, fontsize=10, fontname=FONT_REGULAR)
            page.insert_text((col_date_x, y), (item.get("set_at") or "")[:10], fontsize=10, fontname=FONT_REGULAR)
            page.insert_text((col_grade_x, y), "—", fontsize=10, fontname=FONT_BOLD, color=(0.7, 0.1, 0.1))
            y += 18

    doc.subset_fonts()  # the two full Noto Sans files were ~90% of the file size
    pdf_bytes = doc.tobytes(garbage=3, deflate=True)
    doc.close()
    return pdf_bytes
