"""Performance views count homework that was never handed in - not only the graded
work - so a student, the tutor and parents see how regularly it gets done."""

import pymupdf

import db
import llm
import performance
from conftest import fetch_one, make_assignment, make_student, make_submission, post


def _set_days_ago(assignment_id, days):
    conn = db.get_db()
    conn.execute("UPDATE homework_assignments SET created_at = datetime('now', ?) WHERE id = ?",
                 (f"-{days} days", assignment_id))
    conn.commit()
    conn.close()


def _student_with_every_kind_of_homework(**student):
    student_id = make_student(**student)
    graded = make_assignment(student_id, title="Graded fractions")
    make_submission(graded, student_id, feedback_published=1, tutor_grade="A", reviewed_at="2026-10-01 10:00:00")
    waiting = make_assignment(student_id, title="Waiting equations")
    make_submission(waiting, student_id)
    missed = make_assignment(student_id, title="Skipped powers")
    fresh = make_assignment(student_id, title="Fresh functions")
    for assignment, days in ((graded, 20), (waiting, 12), (missed, 10), (fresh, 2)):
        _set_days_ago(assignment, days)
    return student_id


def test_homework_left_without_photos_for_a_week_counts_as_not_handed_in():
    """Homework still within its week is neither handed in nor missed; homework
    waiting for the tutor is handed in."""
    student_id = _student_with_every_kind_of_homework()
    conn = db.get_db()
    try:
        record = performance.homework_record(conn, student_id)
    finally:
        conn.close()

    assert (record["handed_in"], record["due"]) == (2, 3)
    assert [m["title"] for m in record["missed"]] == ["Skipped powers"]
    assert [g["assignment_title"] for g in record["graded"]] == ["Graded fractions"]
    assert (record["letter"], record["gpa"]) == ("A", 4.0)  # missed homework doesn't touch the average


def test_the_student_sees_what_was_not_handed_in(student_client):
    student_id = _student_with_every_kind_of_homework(language="ru")
    html = student_client(student_id, lang="ru").get("/me/performance").get_data(as_text=True)

    assert "Сдано 2 из 3" in html and "Skipped powers" in html and "Fresh functions" not in html


def test_the_tutor_sees_what_was_not_handed_in(admin):
    student_id = _student_with_every_kind_of_homework()
    html = admin.get(f"/admin/students/{student_id}/performance").get_data(as_text=True)

    assert "Handed in 2 of 3" in html and "Skipped powers" in html and "Fresh functions" not in html


def test_the_parent_report_lists_homework_not_handed_in_with_a_fresh_summary(fake_llm, admin):
    student_id = _student_with_every_kind_of_homework()
    fake_llm.reply("text", "Fresh summary mentioning the skipped homework.")

    response = admin.get(f"/admin/students/{student_id}/performance.pdf")

    assert response.status_code == 200
    text = pymupdf.open(stream=response.data, filetype="pdf")[0].get_text()
    assert "2 of 3 homework assignments set" in text and "Not handed in" in text and "Skipped powers" in text
    assert "Fresh summary" in text  # regenerated before the report, so it knows about the missed homework


def test_the_parent_report_still_downloads_when_the_summary_fails(monkeypatch, admin):
    student_id = _student_with_every_kind_of_homework()
    conn = db.get_db()
    conn.execute("UPDATE students SET performance_narrative = 'Old summary' WHERE id = ?", (student_id,))
    conn.commit()
    conn.close()

    def down(*args, **kwargs):
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "complete", down)
    response = admin.get(f"/admin/students/{student_id}/performance.pdf")

    assert response.status_code == 200
    assert "Old summary" in pymupdf.open(stream=response.data, filetype="pdf")[0].get_text()


def test_the_summary_is_told_about_homework_not_handed_in(fake_llm):
    student_id = _student_with_every_kind_of_homework()
    fake_llm.reply("text", "summary")

    performance.refresh_narrative(student_id)

    sent = fake_llm.calls[-1]["messages"]
    assert "not handed in" in sent[0]["content"].lower()
    assert "Handed in: 2 of 3" in sent[1]["content"] and "Not handed in: Skipped powers" in sent[1]["content"]
    assert "Fresh functions" not in sent[1]["content"]


def test_a_student_who_handed_nothing_in_still_gets_a_summary(fake_llm):
    student_id = make_student()
    _set_days_ago(make_assignment(student_id, title="Skipped powers"), 9)
    fake_llm.reply("text", "Nothing handed in yet - let's start with the next one.")

    performance.refresh_narrative(student_id)

    assert fetch_one("SELECT performance_narrative FROM students WHERE id = ?", (student_id,))[0].startswith("Nothing")


def test_setting_new_homework_refreshes_the_summary(fake_llm, admin):
    """A homework becomes "not handed in" a week after it's set, with no event of its
    own - setting the next one is when the summary catches up."""
    student_id = _student_with_every_kind_of_homework()
    fake_llm.reply("text", "Updated summary")

    post(admin, f"/admin/students/{student_id}/assignments", {"title": "Next homework"})

    assert fetch_one("SELECT performance_narrative FROM students WHERE id = ?", (student_id,))[0] == "Updated summary"
