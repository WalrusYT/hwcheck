"""Password hashing and login-required decorators for both the tutor (admin) and student areas."""

from functools import wraps

from flask import redirect, request, session, url_for
from werkzeug.security import check_password_hash, generate_password_hash


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
