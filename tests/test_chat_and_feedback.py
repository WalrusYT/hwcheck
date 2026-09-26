import json

import llm
from conftest import CSRF, fetch_one, make_assignment, make_student, make_submission, post


def chat(client, assignment_id, **payload):
    return client.post(f"/me/homeworks/{assignment_id}/chat", json=payload, headers={"X-CSRF-Token": CSRF})


def test_hint_uses_the_students_curriculum_language_and_the_assignment_topic(fake_llm, student_client):
    student_id = make_student(language="ru", curriculum="pt", school_year="9.º ano", tutor_notes="weak at fractions")
    assignment_id = make_assignment(student_id, title="Semelhança", topic="Critérios de semelhança")
    fake_llm.reply("text", "Подсказка")

    response = chat(student_client(student_id, "ru"), assignment_id, action="theory")

    assert response.status_code == 200
    system = fake_llm.calls[0]["messages"][0]["content"]
    for expected in ("Semelhança", "Critérios de semelhança", "9.º ano", "weak at fractions",
                     "Portuguese national curriculum", "Write in Russian", '"ты"'):
        assert expected in system


def test_failed_hint_refunds_the_coin_and_hides_internal_errors(monkeypatch, student_client):
    student_id = make_student()
    assignment_id = make_assignment(student_id)

    def down(*args, **kwargs):
        raise llm.LLMError("RateLimitError: org-secret123 exceeded")

    monkeypatch.setattr(llm, "complete", down)
    response = chat(student_client(student_id), assignment_id, action="theory")

    assert response.status_code == 502
    assert "org-secret123" not in response.get_data(as_text=True)
    assert fetch_one("SELECT COUNT(*) AS c FROM hint_chat_messages")["c"] == 0


def test_hint_limit_is_enforced_server_side(fake_llm, student_client):
    student_id = make_student()
    assignment_id = make_assignment(student_id)
    fake_llm.reply("text", "hint")
    client = student_client(student_id)
    for _ in range(3):
        assert chat(client, assignment_id, action="theory").status_code == 200
    assert chat(client, assignment_id, action="theory").status_code == 403


def test_publishing_notifies_in_the_students_language_and_refreshes_the_narrative(fake_llm, admin):
    student_id = make_student(language="ru")
    assignment_id = make_assignment(student_id, title="Дроби")
    submission_id = make_submission(assignment_id, student_id, ai_status="done",
                                    ai_result=json.dumps({"problems": [], "overall_summary": "", "estimated_score": "",
                                                          "flags_for_tutor": []}))
    fake_llm.reply("text", "Новая сводка")

    response = post(admin, f"/admin/submissions/{submission_id}", {"grade": "B", "tutor_comment": "", "action": "publish"})

    assert response.status_code == 302
    notification = fetch_one("SELECT title FROM notifications WHERE recipient_type = 'student'")
    assert notification["title"] == "«Дроби» проверено. Оценка: B"
    assert fetch_one("SELECT performance_narrative FROM students WHERE id = ?", (student_id,))[0] == "Новая сводка"


def test_narrative_failure_keeps_the_previous_narrative(monkeypatch):
    import db
    import performance

    student_id = make_student()
    conn = db.get_db()
    conn.execute("UPDATE students SET performance_narrative = 'old' WHERE id = ?", (student_id,))
    conn.commit()
    conn.close()

    def down(*args, **kwargs):
        raise llm.LLMError("down")

    monkeypatch.setattr(llm, "complete", down)
    make_submission(make_assignment(student_id), student_id, feedback_published=1, tutor_grade="A")
    performance.refresh_narrative(student_id)

    assert fetch_one("SELECT performance_narrative FROM students WHERE id = ?", (student_id,))[0] == "old"


def test_admin_can_set_curriculum_profile_and_blank_names_are_refused(admin):
    student_id = make_student()
    post(admin, f"/admin/students/{student_id}/update",
         {"name": "Ana", "curriculum": "pt", "school_year": "9.º ano", "language": "ru", "tutor_notes": "n"})
    row = fetch_one("SELECT name, curriculum, school_year, language FROM students WHERE id = ?", (student_id,))
    assert tuple(row) == ("Ana", "pt", "9.º ano", "ru")

    post(admin, f"/admin/students/{student_id}/update", {"name": "   ", "curriculum": "ru"})
    assert fetch_one("SELECT name FROM students WHERE id = ?", (student_id,))["name"] == "Ana"


def test_recheck_keeps_student_answers_the_tutor_corrected(monkeypatch, admin):
    student_id = make_student()
    ai = {"problems": [{"problem_label": "1", "student_answer": "x=4"}, {"problem_label": "2", "student_answer": "7"}]}
    tutor = [{"problem_label": "1", "student_answer": "x=3"}, {"problem_label": "2", "student_answer": "7"}]
    submission_id = make_submission(make_assignment(student_id), student_id, ai_status="done",
                                    ai_result=json.dumps(ai), tutor_result=json.dumps(tutor))
    started = {}
    import grading_jobs
    monkeypatch.setattr(grading_jobs, "start_grading_job", lambda *a, **k: started.update(k))

    post(admin, f"/admin/submissions/{submission_id}/regrade",
         {"problem_count": "1", "problem_label_0": "1", "ai_note_0": "misread"})

    assert started["known_answers"] == {"1": "x=3"}
