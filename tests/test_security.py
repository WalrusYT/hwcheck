import re

import pytest

from conftest import CSRF, fetch_one, make_assignment, make_student, make_submission, post


@pytest.mark.parametrize("target", ["https://evil.example/phish", "//evil.example", "/\\evil.example", "javascript:alert(1)"])
def test_student_login_never_redirects_off_site(anon, target):
    make_student(username="alice", password="Correct-Horse-9")
    response = post(anon, f"/me/login?next={target}", {"username": "alice", "password": "Correct-Horse-9"})
    assert response.status_code == 302
    assert response.headers["Location"] == "/me/"


def test_student_login_follows_a_local_next(anon):
    make_student(username="alice", password="Correct-Horse-9")
    response = post(anon, "/me/login?next=/me/homeworks", {"username": "alice", "password": "Correct-Horse-9"})
    assert response.headers["Location"] == "/me/homeworks"


def test_admin_login_never_redirects_off_site(anon):
    response = post(anon, "/admin/login?next=https://evil.example", {"password": "test-admin-password-123"})
    assert response.headers["Location"] == "/admin"


def test_post_without_csrf_token_is_rejected(admin):
    student_id = make_student()
    response = admin.post(f"/admin/students/{student_id}/delete")
    assert response.status_code == 302 and response.headers["Location"] == f"/admin/students/{student_id}/delete"
    assert fetch_one("SELECT id FROM students WHERE id = ?", (student_id,)) is not None


def test_post_with_wrong_csrf_token_is_rejected(admin):
    student_id = make_student()
    admin.post(f"/admin/students/{student_id}/delete", data={"csrf_token": "forged"})
    assert fetch_one("SELECT id FROM students WHERE id = ?", (student_id,)) is not None


def test_stale_page_sends_the_student_back_with_a_message_in_their_language(student_client):
    """A homework page opened before a deploy (or in a long-forgotten tab) has no valid
    token: the student used to land on an English error page with their photos lost."""
    student_id = make_student(language="ru")
    assignment_id = make_assignment(student_id)
    client = student_client(student_id)
    with client.session_transaction() as s:
        s["lang"] = "ru"

    response = client.post(f"/me/homeworks/{assignment_id}", data={"csrf_token": "from-an-old-page"})

    assert response.status_code == 302 and response.headers["Location"] == f"/me/homeworks/{assignment_id}"
    page = client.get(f"/me/homeworks/{assignment_id}").get_data(as_text=True)
    assert "Страница устарела" in page
    assert fetch_one("SELECT id FROM student_submissions WHERE assignment_id = ?", (assignment_id,)) is None


def test_csrf_failure_on_an_unknown_path_is_not_an_open_redirect(admin):
    response = admin.post("//evil.example/x")
    assert response.status_code == 400


def test_json_post_needs_the_csrf_header(student_client):
    student_id = make_student()
    assignment_id = make_assignment(student_id)
    client = student_client(student_id)
    without = client.post(f"/me/homeworks/{assignment_id}/chat", json={"action": "theory"})
    assert without.status_code == 400 and without.is_json


def test_every_post_form_carries_the_csrf_token(admin, student_client):
    """Guards future templates too: a form without the token would 400 in production."""
    student_id = make_student()
    assignment_id = make_assignment(student_id)
    submission_id = make_submission(assignment_id, student_id, ai_status="error", ai_error="boom")
    admin_pages = ["/admin", "/admin/students", f"/admin/students/{student_id}", f"/admin/submissions/{submission_id}"]
    pages = [(admin, url) for url in admin_pages]
    student = student_client(student_id)
    make_submission(make_assignment(student_id, title="Unsubmitted-free"), student_id)
    pages += [(student, url) for url in ["/me/", "/me/homeworks", f"/me/homeworks/{assignment_id}", "/me/change-password"]]
    for client, url in pages:
        html = client.get(url).get_data(as_text=True)
        forms = re.findall(r"<form\b[^>]*method=\"post\"[^>]*>(.*?)</form>", html, re.S | re.I)
        assert forms, f"expected POST forms on {url}"
        for form in forms:
            assert f'name="csrf_token" value="{CSRF}"' in form, f"form without CSRF token on {url}"


def test_admin_login_locks_out_after_repeated_failures(anon):
    for _ in range(5):
        assert post(anon, "/admin/login", {"password": "wrong"}).status_code == 200
    blocked = post(anon, "/admin/login", {"password": "test-admin-password-123"})
    assert blocked.status_code == 429
    assert "Too many failed attempts" in blocked.get_data(as_text=True)


def test_successful_student_login_clears_failures(anon):
    make_student(username="alice", password="Correct-Horse-9")
    for _ in range(9):
        post(anon, "/me/login", {"username": "alice", "password": "nope"})
    assert post(anon, "/me/login", {"username": "alice", "password": "Correct-Horse-9"}).status_code == 302
    assert fetch_one("SELECT COUNT(*) AS c FROM login_attempts")["c"] == 0


def test_session_cookie_flags(app):
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


def test_student_cannot_open_another_students_assignment(student_client):
    alice = make_student(username="alice")
    bob = make_student(username="bob")
    bobs_assignment = make_assignment(bob)
    assert student_client(alice).get(f"/me/homeworks/{bobs_assignment}").status_code == 404


def test_file_routes_only_serve_files_listed_in_the_database(admin, student_client, tmp_path):
    from config import SUBMISSION_FILES_DIR

    student_id = make_student()
    assignment_id = make_assignment(student_id)
    submission_id = make_submission(assignment_id, student_id, files='["00_page.jpg"]')
    folder = SUBMISSION_FILES_DIR / str(submission_id)
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "00_page.jpg").write_bytes(b"listed")
    (folder / "stray.jpg").write_bytes(b"not listed")

    assert admin.get(f"/admin/submission-files/{submission_id}/00_page.jpg").status_code == 200
    assert admin.get(f"/admin/submission-files/{submission_id}/stray.jpg").status_code == 404
    student = student_client(student_id)
    assert student.get(f"/me/submissions/{submission_id}/files/00_page.jpg").status_code == 200
    assert student.get(f"/me/submissions/{submission_id}/files/stray.jpg").status_code == 404
