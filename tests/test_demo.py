"""The guest demo: a made-up student area for people who haven't booked lessons.
It must never show a real student's data, change anything, or call the AI."""

import io

import demo
import notifications
from conftest import CSRF, fetch_one, make_assignment, make_student, make_submission, post


def _guest(anon, lang=None):
    anon.get("/me/demo" + (f"?lang={lang}" if lang else ""))
    return anon


def _real_student_with_secrets():
    student = make_student(name="Real Person", username="real.person")
    assignment = make_assignment(student, title="Secret homework", topic="Private topic")
    make_submission(assignment, student, tutor_grade="F", tutor_comment="Secret comment", feedback_published=1,
                    reviewed_at="2026-10-01 10:00:00")
    notifications.notify_student(student, "new_assignment", "Secret note", link=f"/me/homeworks/{assignment}")
    return student, assignment


def _ask(client, assignment, payload):
    return client.post(f"/me/homeworks/{assignment}/chat", json=payload, headers={"X-CSRF-Token": CSRF})


def _demo_rows(sql, params=()):
    conn = demo.get_db("en")
    rows = conn.execute(sql, params).fetchall()
    conn.close()
    return rows


def _demo_assignment(title, lang="en"):
    conn = demo.get_db(lang)
    row = conn.execute("SELECT id FROM homework_assignments WHERE title = ? AND student_id = ?",
                       (title, demo.STUDENT_ID)).fetchone()
    conn.close()
    return row["id"]


def test_a_guest_sees_the_demo_student_and_never_a_real_one(anon):
    """The demo student has id 1 in the demo database - so does the first real
    student. Every page a guest opens must come from the demo database."""
    _real_student_with_secrets()
    guest = _guest(anon)

    pages = ["/me/", "/me/homeworks", "/me/performance"]
    pages += [f"/me/homeworks/{_demo_assignment(t)}" for t in ("Equações do 1.º grau", "Potências e raízes")]
    for page in pages:
        response = guest.get(page)
        html = response.get_data(as_text=True)
        assert response.status_code == 200, page
        assert "Secret" not in html and "Real Person" not in html and "Private topic" not in html, page
    dashboard = guest.get("/me/").get_data(as_text=True)
    assert "Alex" in dashboard and "Equações do 1.º grau" in dashboard
    assert demo.BOOK_URL in dashboard  # the "book a lesson" banner


def test_switching_language_switches_the_demo_student_without_touching_the_database(anon):
    real, _ = _real_student_with_secrets()
    guest = _guest(anon)

    post(guest, "/me/language/ru")

    html = guest.get("/me/").get_data(as_text=True)
    assert "Саша" in html and "Записаться на урок" in html
    assert fetch_one("SELECT language FROM students WHERE id = ?", (real,))["language"] == "en"


def test_switching_language_on_a_homework_page_stays_on_that_homework(anon):
    """Each language had its own demo student with its own homework ids, so switching
    to RU on a homework page led to a 404."""
    guest = _guest(anon)
    page = f"/me/homeworks/{_demo_assignment('Equações do 1.º grau')}"
    guest.get(page)

    response = post(guest, "/me/language/ru", headers={"Referer": f"http://localhost{page}"})

    assert response.headers["Location"].endswith(page)
    html = guest.get(page).get_data(as_text=True)
    assert "Хорошая работа" in html  # the tutor's comment, in Russian


def test_a_guest_cannot_change_anything(anon):
    real, assignment = _real_student_with_secrets()
    guest = _guest(anon)
    homework = _demo_assignment("Potências e raízes")
    sent = _demo_assignment("Funções afins")
    before = {table: fetch_one(f"SELECT COUNT(*) AS n FROM {table}")["n"]
              for table in ("student_submissions", "hint_chat_messages", "notifications", "students")}

    attempts = [
        (f"/me/homeworks/{homework}", {"files": (io.BytesIO(b"\xff\xd8 photo"), "page.jpg")}),
        (f"/me/homeworks/{assignment}", {"files": (io.BytesIO(b"\xff\xd8 photo"), "page.jpg")}),
        (f"/me/homeworks/{sent}/remove", {}),
        ("/me/notifications/mark-all-read", {}),
        ("/me/change-password", {"current_password": "x", "new_password": "Long-enough-9", "confirm_password": "Long-enough-9"}),
    ]
    for url, data in attempts:
        response = post(guest, url, data, content_type="multipart/form-data")
        assert response.status_code == 302, url

    after = {table: fetch_one(f"SELECT COUNT(*) AS n FROM {table}")["n"] for table in before}
    assert after == before
    conn = demo.get_db("en")
    assert conn.execute("SELECT COUNT(*) FROM student_submissions WHERE assignment_id = ?", (homework,)).fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM student_submissions WHERE assignment_id = ?", (sent,)).fetchone()[0] == 1
    conn.close()
    assert "This is a demo" in guest.get("/me/").get_data(as_text=True)


def test_the_hint_helper_answers_a_guest_with_an_example_and_no_ai_call(anon):
    """No fake_llm here: the autouse no_network fixture fails the test on any model call."""
    guest = _guest(anon)
    homework = _demo_assignment("Potências e raízes")

    response = _ask(guest, homework, {"action": "task_help", "task_number": "3"})

    assert response.status_code == 200
    data = response.get_json()
    assert data["reply"].startswith("Task 3:") and data["remaining"] == 1  # one hint was already used
    conn = demo.get_db("en")
    assert conn.execute("SELECT COUNT(*) FROM hint_chat_messages WHERE assignment_id = ?", (homework,)).fetchone()[0] == 2
    conn.close()
    assert _ask(guest, homework, {"action": "anything"}).status_code == 400


def test_a_guest_gets_the_demo_sheets_and_notifications(anon):
    guest = _guest(anon)
    homework = _demo_assignment("Equações do 1.º grau")

    sheet = guest.get(f"/me/homeworks/{homework}/task-files/sheet.png")
    assert sheet.status_code == 200 and sheet.mimetype == "image/png"
    assert guest.get(f"/me/homeworks/{homework}/task-files/../../demo.db").status_code == 404
    assert guest.get("/me/submissions/1/files/00_photo.jpg").status_code == 404
    html = guest.get("/me/").get_data(as_text=True)
    assert "Equações do 1.º grau" in html and "has been graded: B" in html  # the bell
    unread_sql = "SELECT id FROM notifications WHERE recipient_id = 1 AND is_read = 0"
    unread = _demo_rows(unread_sql)
    assert guest.get(f"/me/notifications/{unread[0]['id']}/open").status_code == 302
    assert len(_demo_rows(unread_sql)) == len(unread)  # opening one changes nothing


def test_a_logged_in_student_stays_themselves(student_client):
    student = make_student(name="Real Person", username="real.person")
    client = student_client(student)

    client.get("/me/demo")

    html = client.get("/me/").get_data(as_text=True)
    assert "Real Person" in html and "Alex" not in html


def test_logging_in_for_real_ends_the_demo(anon):
    make_student(name="Real Person", username="real.person", password="Correct-Horse-9")
    guest = _guest(anon)

    post(guest, "/me/login", {"username": "real.person", "password": "Correct-Horse-9"})

    html = guest.get("/me/").get_data(as_text=True)
    assert "Real Person" in html and demo.BOOK_URL not in html


def test_the_login_page_offers_the_demo_in_both_languages(anon):
    assert "/me/demo" in anon.get("/me/login").get_data(as_text=True)
    post(anon, "/me/language/ru")
    assert "Посмотреть как гость" in anon.get("/me/login").get_data(as_text=True)


def test_leaving_the_demo_logs_the_guest_out(anon):
    guest = _guest(anon, lang="ru")
    assert "Саша" in guest.get("/me/").get_data(as_text=True)

    guest.get("/me/logout")

    assert guest.get("/me/").status_code == 302
