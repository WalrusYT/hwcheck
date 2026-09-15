"""TutorIlya Homework: student portal with AI-assisted homework grading for the tutor."""

import json
import os

from dotenv import load_dotenv
from flask import Flask, redirect, render_template, session, url_for

load_dotenv()

import db
import notifications
from admin_routes import admin_bp
from config import ASSIGNMENT_FILES_DIR, SUBMISSION_FILES_DIR, UPLOAD_DIR
from student_routes import student_bp
from translations import t

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB per request
app.jinja_env.filters["fromjson"] = json.loads
app.jinja_env.globals["t"] = t


def wrap_math(value):
    """Wrap a short math-only string (never prose) in LaTeX inline delimiters
    for KaTeX rendering, unless it's already delimited. The AI grader is
    inconsistent about adding \\( \\) itself in these fields, but they're
    always pure expressions, so it's safe to always wrap them here."""
    if not value:
        return value
    stripped = value.strip()
    already_wrapped = (
        (stripped.startswith("\\(") and stripped.endswith("\\)"))
        or (stripped.startswith("\\[") and stripped.endswith("\\]"))
        or (stripped.startswith("$") and stripped.endswith("$") and len(stripped) > 1)
    )
    if already_wrapped:
        return value
    return f"\\({value}\\)"


app.jinja_env.filters["wrap_math"] = wrap_math

db.init_db()

# A submission's AI grading runs on a background thread (grading_jobs.py); if the
# process restarts mid-grade (crash, OOM, deploy) that thread dies with it, leaving
# the row stuck on "pending" with no background job left to ever finish it. Surface
# that as a retryable error instead of an infinite spinner.
_startup_conn = db.get_db()
_startup_conn.execute(
    "UPDATE student_submissions SET ai_status = 'error', "
    "ai_error = 'Grading was interrupted by a server restart. Click Retry AI grading below.' "
    "WHERE ai_status = 'pending'"
)
_startup_conn.commit()
_startup_conn.close()

UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ASSIGNMENT_FILES_DIR.mkdir(parents=True, exist_ok=True)
SUBMISSION_FILES_DIR.mkdir(parents=True, exist_ok=True)

app.register_blueprint(admin_bp)
app.register_blueprint(student_bp)


@app.context_processor
def inject_notifications():
    ctx = {}
    if session.get("is_admin"):
        ctx["admin_notifications"] = notifications.get_admin_notifications(limit=8)
        ctx["admin_unread_count"] = notifications.count_unread_admin()
    if session.get("student_id"):
        ctx["student_notifications"] = notifications.get_student_notifications(session["student_id"], limit=8)
        ctx["student_unread_count"] = notifications.count_unread_student(session["student_id"])
    return ctx


@app.route("/")
def index():
    return redirect(url_for("student.login"))


@app.route("/favicon.ico")
def favicon():
    # Browsers probe this legacy path regardless of our <link rel="icon"> tags.
    return redirect(url_for("static", filename="favicon.png"))


@app.errorhandler(413)
def too_large(_exc):
    return render_template("error.html", message="Those files are too large (20 MB max total). Try smaller photos or fewer pages."), 413


@app.errorhandler(404)
def not_found(_exc):
    return render_template("error.html", message="Page not found."), 404


@app.errorhandler(405)
def method_not_allowed(_exc):
    return render_template("error.html", message="That action can't be reached directly - go back and use the button/link for it instead."), 405


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug, port=int(os.environ.get("PORT", 5050)))
