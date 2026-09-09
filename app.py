"""HWCheck: student homework submission + AI-assisted grading for the tutor."""

import json
import os
import secrets
import sqlite3
import string
from functools import wraps
from pathlib import Path

from dotenv import load_dotenv
from flask import (
    Flask,
    abort,
    flash,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

load_dotenv()

import db
from grading import GradingError, grade_submission

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
UPLOAD_DIR = DATA_DIR / "uploads"
HOMEWORK_FILES_DIR = UPLOAD_DIR / "homeworks"
ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}
MAX_FILES = 10

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")
app.config["MAX_CONTENT_LENGTH"] = 20 * 1024 * 1024  # 20 MB per request
app.jinja_env.filters["fromjson"] = json.loads

db.init_db()
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
HOMEWORK_FILES_DIR.mkdir(parents=True, exist_ok=True)


def generate_code():
    alphabet = string.ascii_uppercase + string.digits
    conn = db.get_db()
    try:
        while True:
            code = "HW-" + "".join(secrets.choice(alphabet) for _ in range(5))
            if not conn.execute("SELECT 1 FROM homeworks WHERE code = ?", (code,)).fetchone():
                return code
    finally:
        conn.close()


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("is_admin"):
            return redirect(url_for("admin_login", next=request.path))
        return view(*args, **kwargs)
    return wrapped


@app.route("/")
def index():
    return redirect(url_for("submit_form"))


# ---- Student-facing submission form -------------------------------------

@app.route("/submit", methods=["GET"])
def submit_form():
    return render_template("submit.html")


@app.route("/submit", methods=["POST"])
def submit_homework():
    student_name = (request.form.get("student_name") or "").strip()
    homework_code = (request.form.get("homework_code") or "").strip().upper()
    files = [f for f in request.files.getlist("files") if f and f.filename]

    errors = []
    if not student_name:
        errors.append("Please enter your name.")
    if not homework_code:
        errors.append("Please enter the homework code your tutor gave you.")
    if not files:
        errors.append("Please attach at least one photo or PDF of your homework.")
    elif len(files) > MAX_FILES:
        errors.append(f"Please attach at most {MAX_FILES} files.")
    for f in files:
        if Path(f.filename).suffix.lower() not in ALLOWED_EXT:
            errors.append(f"Unsupported file type: {f.filename}. Use a photo (jpg/png/webp) or PDF.")

    conn = db.get_db()
    homework = None
    if homework_code:
        homework = conn.execute("SELECT * FROM homeworks WHERE code = ?", (homework_code,)).fetchone()
        if not homework:
            errors.append("That homework code wasn't found. Double-check it with your tutor.")

    if errors:
        conn.close()
        return render_template(
            "submit.html", errors=errors, student_name=student_name, homework_code=homework_code
        ), 400

    cur = conn.execute(
        "INSERT INTO submissions (homework_code, student_name) VALUES (?, ?)",
        (homework_code, student_name),
    )
    submission_id = cur.lastrowid
    conn.commit()

    sub_dir = UPLOAD_DIR / str(submission_id)
    sub_dir.mkdir(parents=True, exist_ok=True)
    saved_names = []
    for i, f in enumerate(files):
        safe = secure_filename(f.filename) or f"file_{i}"
        dest = sub_dir / f"{i:02d}_{safe}"
        f.save(dest)
        saved_names.append(dest.name)
    conn.execute("UPDATE submissions SET files = ? WHERE id = ?", (json.dumps(saved_names), submission_id))
    conn.commit()

    task_file_names = json.loads(homework["task_files"] or "[]") if homework else []
    task_file_paths = [HOMEWORK_FILES_DIR / homework_code / n for n in task_file_names]

    try:
        result = grade_submission(
            [sub_dir / n for n in saved_names],
            student_name,
            homework["topic"] if homework else None,
            task_file_paths=task_file_paths,
        )
        conn.execute(
            "UPDATE submissions SET ai_result = ?, ai_status = 'done' WHERE id = ?",
            (json.dumps(result), submission_id),
        )
    except GradingError as exc:
        conn.execute(
            "UPDATE submissions SET ai_status = 'error', ai_error = ? WHERE id = ?",
            (str(exc), submission_id),
        )
    conn.commit()
    conn.close()

    return render_template("submitted.html", student_name=student_name)


# ---- Admin (tutor) area ---------------------------------------------------

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        expected = os.environ.get("ADMIN_PASSWORD")
        if not expected:
            error = "ADMIN_PASSWORD is not set on the server - check .env."
        elif secrets.compare_digest(password, expected):
            session["is_admin"] = True
            return redirect(request.args.get("next") or url_for("admin_dashboard"))
        else:
            error = "Wrong password."
    return render_template("admin_login.html", error=error)


@app.route("/admin/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin_login"))


@app.route("/admin")
@admin_required
def admin_dashboard():
    conn = db.get_db()
    submissions = conn.execute(
        "SELECT * FROM submissions ORDER BY submitted_at DESC LIMIT 200"
    ).fetchall()
    conn.close()
    return render_template("admin_dashboard.html", submissions=submissions)


@app.route("/admin/homeworks", methods=["GET", "POST"])
@admin_required
def admin_homeworks():
    conn = db.get_db()
    if request.method == "POST":
        student_name = (request.form.get("student_name") or "").strip()
        topic = (request.form.get("topic") or "").strip()
        code = (request.form.get("code") or "").strip().upper() or generate_code()
        task_files = [f for f in request.files.getlist("task_files") if f and f.filename]

        errors = []
        if not student_name:
            errors.append("Student name is required.")
        for f in task_files:
            if Path(f.filename).suffix.lower() not in ALLOWED_EXT:
                errors.append(f"Unsupported file type: {f.filename}. Use a photo (jpg/png/webp) or PDF.")

        if errors:
            for e in errors:
                flash(e)
        else:
            code_dir = HOMEWORK_FILES_DIR / code
            saved_names = []
            if task_files:
                code_dir.mkdir(parents=True, exist_ok=True)
                for i, f in enumerate(task_files):
                    safe = secure_filename(f.filename) or f"file_{i}"
                    dest = code_dir / f"{i:02d}_{safe}"
                    f.save(dest)
                    saved_names.append(dest.name)
            try:
                conn.execute(
                    "INSERT INTO homeworks (code, student_name, topic, task_files) VALUES (?, ?, ?, ?)",
                    (code, student_name, topic, json.dumps(saved_names)),
                )
                conn.commit()
                flash(f"Created homework code {code} for {student_name}.")
            except sqlite3.IntegrityError:
                flash(f"Code {code} is already in use - pick another.")
    homeworks = conn.execute("SELECT * FROM homeworks ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template("admin_homeworks.html", homeworks=homeworks, suggested_code=generate_code())


@app.route("/admin/submissions/<int:submission_id>", methods=["GET", "POST"])
@admin_required
def admin_submission_detail(submission_id):
    conn = db.get_db()
    submission = conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()
    if not submission:
        conn.close()
        abort(404)

    if request.method == "POST":
        notes = request.form.get("tutor_notes", "")
        status = "reviewed" if request.form.get("mark_reviewed") else "new"
        conn.execute(
            "UPDATE submissions SET tutor_notes = ?, tutor_status = ? WHERE id = ?",
            (notes, status, submission_id),
        )
        conn.commit()
        submission = conn.execute("SELECT * FROM submissions WHERE id = ?", (submission_id,)).fetchone()

    homework = conn.execute(
        "SELECT * FROM homeworks WHERE code = ?", (submission["homework_code"],)
    ).fetchone()
    conn.close()

    files = json.loads(submission["files"] or "[]")
    task_files = json.loads(homework["task_files"] or "[]") if homework else []
    ai_result = json.loads(submission["ai_result"]) if submission["ai_result"] else None

    return render_template(
        "admin_submission_detail.html",
        submission=submission,
        homework=homework,
        files=files,
        task_files=task_files,
        ai_result=ai_result,
    )


@app.route("/admin/uploads/<int:submission_id>/<path:filename>")
@admin_required
def uploaded_file(submission_id, filename):
    return send_from_directory(UPLOAD_DIR / str(submission_id), filename)


@app.route("/admin/homework-files/<code>/<path:filename>")
@admin_required
def homework_task_file(code, filename):
    return send_from_directory(HOMEWORK_FILES_DIR / code, filename)


@app.errorhandler(413)
def too_large(_exc):
    return render_template("submit.html", errors=["Those files are too large (20 MB max total). Try smaller photos or fewer pages."]), 413


if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(debug=debug, port=int(os.environ.get("PORT", 5050)))
