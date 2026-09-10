"""Builds a simple one-page performance report PDF for a student, to send to parents."""

from datetime import datetime, timezone

import pymupdf as fitz

PAGE_WIDTH, PAGE_HEIGHT = fitz.paper_size("a4")
MARGIN = 50


def build_performance_pdf(student_name, average_letter, average_gpa, history, narrative):
    """history: list of {"title": str, "submitted_at": str, "grade": str}, most recent first.
    Returns PDF bytes.
    """
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
    y = MARGIN

    page.insert_text((MARGIN, y), "Performance Report", fontsize=20, fontname="helv")
    y += 26
    page.insert_text((MARGIN, y), student_name, fontsize=14, fontname="helv")
    y += 18
    generated = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    page.insert_text((MARGIN, y), f"Generated {generated}", fontsize=9, color=(0.4, 0.4, 0.4))
    y += 30

    page.insert_text((MARGIN, y), "Average grade:", fontsize=12, fontname="helv")
    avg_text = f"{average_letter} ({average_gpa}/4.0)" if average_letter else "No graded homework yet"
    page.insert_text((MARGIN + 130, y), avg_text, fontsize=12, fontname="helv")
    y += 30

    if narrative:
        rect = fitz.Rect(MARGIN, y, PAGE_WIDTH - MARGIN, y + 90)
        page.insert_textbox(rect, narrative, fontsize=10.5, lineheight=1.4)
        y += 100

    y += 10
    page.insert_text((MARGIN, y), "Grade history", fontsize=13, fontname="helv")
    y += 10
    page.draw_line((MARGIN, y), (PAGE_WIDTH - MARGIN, y), color=(0.7, 0.7, 0.7))
    y += 18

    col_title_x = MARGIN
    col_date_x = PAGE_WIDTH - MARGIN - 180
    col_grade_x = PAGE_WIDTH - MARGIN - 60

    page.insert_text((col_title_x, y), "Homework", fontsize=9, color=(0.4, 0.4, 0.4))
    page.insert_text((col_date_x, y), "Date", fontsize=9, color=(0.4, 0.4, 0.4))
    page.insert_text((col_grade_x, y), "Grade", fontsize=9, color=(0.4, 0.4, 0.4))
    y += 14
    page.draw_line((MARGIN, y), (PAGE_WIDTH - MARGIN, y), color=(0.85, 0.85, 0.85))
    y += 14

    for item in history:
        if y > PAGE_HEIGHT - MARGIN:
            page = doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            y = MARGIN

        title = item["title"]
        if len(title) > 45:
            title = title[:42] + "..."
        page.insert_text((col_title_x, y), title, fontsize=10)
        date_str = (item.get("submitted_at") or "")[:10]
        page.insert_text((col_date_x, y), date_str, fontsize=10)
        page.insert_text((col_grade_x, y), item["grade"], fontsize=10, fontname="helv")
        y += 18

    if not history:
        page.insert_text((MARGIN, y), "No graded homework yet.", fontsize=10, color=(0.5, 0.5, 0.5))

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes
