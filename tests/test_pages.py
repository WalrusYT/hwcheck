"""The redesigned pages: what each one shows, and to whom."""

import json
import re

from conftest import make_assignment, make_student, make_submission


def _between(html, start, end):
    return html[html.index(start):html.index(end) if end else len(html)]


def test_home_groups_homework_by_status_and_shows_only_the_students_own(student_client):
    ana = make_student(name="Ana", username="ana")
    other = make_student(name="Bo", username="bo")
    make_assignment(ana, title="Equações 1")
    waiting = make_assignment(ana, title="Semelhança")
    make_submission(waiting, ana)
    done = make_assignment(ana, title="Potências")
    make_submission(done, ana, feedback_published=1, tutor_grade="A", tutor_comment="Great work",
                    reviewed_at="2026-10-13 10:00:00")
    make_assignment(other, title="Not yours")

    html = student_client(ana).get("/me/").get_data(as_text=True)

    assert "Not yours" not in html
    assert "Equações 1" in _between(html, 'data-column="todo"', 'data-column="waiting"')
    assert "Semelhança" in _between(html, 'data-column="waiting"', 'data-column="reviewed"')
    reviewed = _between(html, 'data-column="reviewed"', 'id="progress"')
    assert "Potências" in reviewed and "Great work" in reviewed


def test_home_shows_the_average_of_published_grades_only(student_client):
    ana = make_student(name="Ana", username="ana")
    for grade, published in (("A", 1), ("C", 1), ("F", 0)):
        a = make_assignment(ana, title=f"HW {grade}")
        make_submission(a, ana, feedback_published=published, tutor_grade=grade, reviewed_at="2026-10-01 10:00:00")

    html = student_client(ana).get("/me/").get_data(as_text=True)

    progress = _between(html, 'id="progress"', None)
    assert re.search(r'data-average="B"', progress)  # (4 + 2) / 2 = 3 -> B; the unpublished F doesn't count


def test_home_works_for_a_brand_new_student(student_client):
    ana = make_student(name="Ana", username="ana")
    response = student_client(ana).get("/me/")
    assert response.status_code == 200


def test_both_languages_render_the_new_pages(student_client):
    ana = make_student(name="Ana", username="ana", language="ru")
    assignment = make_assignment(ana, title="Equações 1")
    client = student_client(ana)
    for lang in ("en", "ru"):
        with client.session_transaction() as s:
            s["lang"] = lang
        for url in ("/me/", "/me/homeworks", f"/me/homeworks/{assignment}", "/me/performance", "/me/change-password"):
            assert client.get(url).status_code == 200, (lang, url)


def test_every_interface_string_exists_in_both_languages():
    import translations
    assert set(translations.STRINGS["en"]) == set(translations.STRINGS["ru"])


def test_review_form_uses_one_tap_verdicts_that_post_the_same_field(admin):
    ana = make_student(name="Ana", username="ana")
    assignment = make_assignment(ana, title="Equações 1")
    result = {"problems": [{"problem_label": "#1", "problem_text": "2x=4", "student_answer": "x=2",
                            "work": "", "correct_answer": "2", "verdict": "partially_correct",
                            "explanation": "", "confidence": "high"}],
              "flags_for_tutor": [], "estimated_score": "0 of 1", "overall_summary": "ok"}
    submission = make_submission(assignment, ana, ai_status="done", ai_result=json.dumps(result))

    html = admin.get(f"/admin/submissions/{submission}").get_data(as_text=True)

    checked = re.findall(r'<input[^>]*name="verdict_0"[^>]*>', html)
    assert len(checked) == 5
    assert [tag for tag in checked if "checked" in tag] == [t for t in checked if 'value="partially_correct"' in t]
    assert 'name="grade"' in html
