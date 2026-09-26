"""Test harness: a throwaway DATA_DIR, no network, synchronous background jobs."""

import json
import os
import sys
import tempfile
from pathlib import Path

# Must happen before any app module is imported: paths are read at import time.
os.environ["DATA_DIR"] = tempfile.mkdtemp(prefix="hwcheck-tests-")
os.environ["FLASK_SECRET_KEY"] = "test-secret"
os.environ["ADMIN_PASSWORD"] = "test-admin-password-123"
os.environ["OPENAI_API_KEY"] = "sk-test-not-real"
os.environ.pop("RENDER", None)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import app as app_module  # noqa: E402
import db  # noqa: E402
import llm  # noqa: E402

CSRF = "test-csrf-token"


class FakeLLM:
    """Scripted replies, keyed by the JSON schema name (or "text" for free-text calls)."""

    def __init__(self):
        self.replies = {}
        self.calls = []

    def reply(self, kind, *payloads):
        self.replies.setdefault(kind, []).extend(payloads)

    def __call__(self, messages, *, model=None, json_schema=None, max_tokens=None, temperature=None):
        kind = json_schema["name"] if json_schema else "text"
        self.calls.append({"kind": kind, "messages": messages, "temperature": temperature})
        queue = self.replies.get(kind)
        if not queue:
            raise AssertionError(f"unexpected {kind} call to the LLM")
        payload = queue.pop(0) if len(queue) > 1 else queue[0]
        if isinstance(payload, Exception):
            raise payload
        return payload if isinstance(payload, str) else json.dumps(payload)


@pytest.fixture(autouse=True)
def fresh_db():
    if db.DB_PATH.exists():
        db.DB_PATH.unlink()
    db.init_db()
    yield


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("a test tried to call the real LLM - use the fake_llm fixture")

    monkeypatch.setattr(llm, "complete", blocked)


@pytest.fixture
def fake_llm(monkeypatch):
    fake = FakeLLM()
    monkeypatch.setattr(llm, "complete", fake)
    return fake


@pytest.fixture(autouse=True)
def synchronous_background_jobs(monkeypatch):
    """Background work finishes before the test's asserts run."""
    import grading_jobs
    import performance

    monkeypatch.setattr(grading_jobs, "_run_in_background", lambda fn: fn())
    monkeypatch.setattr(performance, "_run_in_background", lambda fn, *args: fn(*args))


@pytest.fixture
def app():
    app_module.app.config["TESTING"] = True
    return app_module.app


def _client(app, **session_values):
    client = app.test_client()
    with client.session_transaction() as session:
        session["_csrf"] = CSRF
        session.update(session_values)
    return client


@pytest.fixture
def anon(app):
    return _client(app)


@pytest.fixture
def admin(app):
    return _client(app, is_admin=True)


@pytest.fixture
def student_client(app):
    def make(student_id, lang="en"):
        return _client(app, student_id=student_id, lang=lang)

    return make


def post(client, url, data=None, **kwargs):
    return client.post(url, data={**(data or {}), "csrf_token": CSRF}, **kwargs)


def make_student(name="Test Student", username="test.student", language="en", curriculum="other",
                 password="Correct-Horse-9", **extra):
    from auth import hash_password

    conn = db.get_db()
    cur = conn.execute(
        "INSERT INTO students (name, username, password_hash, language, curriculum, school_year, tutor_notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, username, hash_password(password), language, curriculum,
         extra.get("school_year"), extra.get("tutor_notes")),
    )
    conn.commit()
    student_id = cur.lastrowid
    conn.close()
    return student_id


def make_assignment(student_id, title="Fractions", topic="Adding fractions", task_files=None):
    conn = db.get_db()
    cur = conn.execute(
        "INSERT INTO homework_assignments (student_id, title, topic, task_files) VALUES (?, ?, ?, ?)",
        (student_id, title, topic, json.dumps(task_files or [])),
    )
    conn.commit()
    assignment_id = cur.lastrowid
    conn.close()
    return assignment_id


def make_submission(assignment_id, student_id, **columns):
    conn = db.get_db()
    fields = {"assignment_id": assignment_id, "student_id": student_id, "files": "[]", **columns}
    cur = conn.execute(
        f"INSERT INTO student_submissions ({', '.join(fields)}) VALUES ({', '.join('?' * len(fields))})",
        tuple(fields.values()),
    )
    conn.commit()
    submission_id = cur.lastrowid
    conn.close()
    return submission_id


def fetch_one(sql, params=()):
    conn = db.get_db()
    row = conn.execute(sql, params).fetchone()
    conn.close()
    return row
