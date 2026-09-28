"""Authentication and request-safety helpers for both the tutor (admin) and student areas:
password hashing, login guards, login rate limiting, CSRF tokens, safe redirects."""

import secrets
from functools import wraps
from urllib.parse import urlsplit

from flask import abort, flash, redirect, request, session, url_for
from markupsafe import Markup
from werkzeug.security import check_password_hash, generate_password_hash

import db
from translations import t

LOGIN_WINDOW_MINUTES = 15
MAX_FAILED_LOGINS = {"admin": 5, "student": 10}


MIN_PASSWORD_LENGTH = 8

COMMON_WEAK_PASSWORDS = {
    "password", "password1", "12345678", "123456789", "qwerty123",
    "letmein", "11111111", "00000000", "abc12345", "iloveyou",
    "admin123", "welcome1", "changeme", "student1", "homework1",
}


def password_error(password, username=None):
    """Return a human-readable error string if the password is too weak, else None."""
    if not password or len(password) < MIN_PASSWORD_LENGTH:
        return f"Password must be at least {MIN_PASSWORD_LENGTH} characters long."
    if password.isdigit():
        return "Password can't be all numbers."
    if len(set(password.lower())) == 1:
        return "Password can't be the same character repeated."
    if password.lower() in COMMON_WEAK_PASSWORDS:
        return "That password is too common - please choose another."
    if username and password.lower() == username.strip().lower():
        return "Password can't be the same as the username."
    return None


def hash_password(plain):
    return generate_password_hash(plain)


def check_password(hash_, plain):
    return check_password_hash(hash_, plain)


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin.admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def student_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("student_id"):
            return redirect(url_for("student.login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


def safe_next_url(target, fallback):
    """Only follow a ?next= that stays on this site. Otherwise a link like
    /me/login?next=https://evil.example sends a student to a phishing page
    right after a real, successful login."""
    if not target:
        return fallback
    parts = urlsplit(target)
    if parts.scheme or parts.netloc or not target.startswith("/") or target.startswith("//") or "\\" in target:
        return fallback
    return target


# ---- Login rate limiting -------------------------------------------------

def login_blocked(scope):
    conn = db.get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM login_attempts WHERE scope = ? AND ip = ? "
        "AND attempted_at > datetime('now', ?)",
        (scope, request.remote_addr, f"-{LOGIN_WINDOW_MINUTES} minutes"),
    ).fetchone()
    conn.close()
    return row["c"] >= MAX_FAILED_LOGINS[scope]


def record_failed_login(scope):
    conn = db.get_db()
    conn.execute("DELETE FROM login_attempts WHERE attempted_at < datetime('now', '-1 day')")
    conn.execute("INSERT INTO login_attempts (scope, ip) VALUES (?, ?)", (scope, request.remote_addr))
    conn.commit()
    conn.close()


def clear_failed_logins(scope):
    conn = db.get_db()
    conn.execute("DELETE FROM login_attempts WHERE scope = ? AND ip = ?", (scope, request.remote_addr))
    conn.commit()
    conn.close()


# ---- CSRF ------------------------------------------------------------------

def csrf_token():
    token = session.get("_csrf")
    if not token:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def csrf_field():
    return Markup(f'<input type="hidden" name="csrf_token" value="{csrf_token()}">')


def verify_csrf():
    """before_request hook: every state-changing request must carry the session's token,
    either as a form field or (for fetch) the X-CSRF-Token header."""
    if request.method in ("GET", "HEAD", "OPTIONS"):
        return
    sent = request.form.get("csrf_token") or request.headers.get("X-CSRF-Token") or ""
    expected = session.get("_csrf") or ""
    if not expected or not secrets.compare_digest(sent, expected):
        # Usually a page left open across a deploy or a logout, not an attack: send a
        # form back to its own page (which re-issues a token, or asks to log in) with a
        # message in the viewer's language. fetch() callers get a 400 they handle.
        back = safe_next_url(request.path, None) if request.url_rule is not None else None
        if back and not request.is_json and "X-CSRF-Token" not in request.headers:
            flash(t("form.expired"))
            return redirect(back)
        abort(400, description="csrf")
