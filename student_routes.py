"""Student-facing portal: login, dashboard, homework list/detail/submit, hint chat, performance."""

import json
import shutil
from pathlib import Path

from flask import (
    Blueprint,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    send_from_directory,
    session,
    url_for,
)
from werkzeug.utils import secure_filename

import db
import grading_jobs
import homework_chat
import notifications
import performance
from auth import check_password, hash_password, password_error, student_required
from config import ALLOWED_EXT, ASSIGNMENT_FILES_DIR, MAX_FILES, SUBMISSION_FILES_DIR
from translations import t

student_bp = Blueprint("student", __name__, url_prefix="/me")


@student_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password", "")
        conn = db.get_db()
        student = conn.execute("SELECT * FROM students WHERE username = ?", (username,)).fetchone()
        if student and check_password(student["password_hash"], password):
            session["student_id"] = student["id"]
            session["lang"] = student["language"]
            if not student["first_login_at"]:
                conn.execute(
                    "UPDATE students SET first_login_at = datetime('now') WHERE id = ?", (student["id"],)
                )
                conn.commit()
                notifications.notify_admin(
                    "first_login",
                    f"{student['name']} logged in for the first time",
                    link=url_for("admin.student_detail", student_id=student["id"]),
                )
            conn.close()
            return redirect(request.args.get("next") or url_for("student.dashboard"))
        conn.close()
        error = t("login.error")
    return render_template("student/login.html", error=error)


@student_bp.route("/logout")
def logout():
    session.pop("student_id", None)
    return redirect(url_for("student.login"))


@student_bp.route("/language/<lang>", methods=["POST"])
def set_language(lang):
    if lang not in ("en", "ru"):
        abort(400)
    session["lang"] = lang
    if session.get("student_id"):
        conn = db.get_db()
        conn.execute("UPDATE students SET language = ? WHERE id = ?", (lang, session["student_id"]))
        conn.commit()
        conn.close()
    return redirect(request.referrer or url_for("student.dashboard"))


@student_bp.route("/")
@student_required
def dashboard():
    conn = db.get_db()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (session["student_id"],)).fetchone()
    conn.close()
    return render_template("student/dashboard.html", student=student)


@student_bp.route("/homeworks")
@student_required
def homeworks():
    conn = db.get_db()
    assignments = conn.execute(
        "SELECT * FROM homework_assignments WHERE student_id = ? ORDER BY created_at DESC",
        (session["student_id"],),
    ).fetchall()
    items = []
    for a in assignments:
        subs = conn.execute(
            "SELECT * FROM student_submissions WHERE assignment_id = ? ORDER BY submitted_at DESC",
            (a["id"],),
        ).fetchall()
        published = next((s for s in subs if s["feedback_published"]), None)
        if published:
            status, grade = "reviewed", published["tutor_grade"]
        elif subs:
            status, grade = "awaiting", None
        else:
            status, grade = "not_submitted", None
        items.append({"assignment": a, "status": status, "grade": grade})
    conn.close()
    return render_template("student/homeworks.html", items=items)


@student_bp.route("/homeworks/<int:assignment_id>", methods=["GET", "POST"])
@student_required
def homework_detail(assignment_id):
    conn = db.get_db()
    assignment = conn.execute(
        "SELECT * FROM homework_assignments WHERE id = ? AND student_id = ?",
        (assignment_id, session["student_id"]),
    ).fetchone()
    if not assignment:
        conn.close()
        abort(404)

    existing = conn.execute(
        "SELECT * FROM student_submissions WHERE assignment_id = ? AND student_id = ?",
        (assignment_id, session["student_id"]),
    ).fetchone()

    errors = []
    if request.method == "POST":
        if existing and existing["feedback_published"]:
            conn.close()
            abort(403)

        files = [f for f in request.files.getlist("files") if f and f.filename]
        if not files:
            errors.append(t("homework.no_files_error"))
        elif len(files) > MAX_FILES:
            errors.append(t("homework.too_many_files", max=MAX_FILES))
        for f in files:
            if Path(f.filename).suffix.lower() not in ALLOWED_EXT:
                errors.append(t("homework.bad_file_type", filename=f.filename))

        if not errors:
            if existing:
                submission_id = existing["id"]
                shutil.rmtree(SUBMISSION_FILES_DIR / str(submission_id), ignore_errors=True)
                conn.execute(
                    """UPDATE student_submissions
                       SET files = '[]', ai_result = NULL, ai_status = 'pending', ai_error = NULL,
                           tutor_grade = NULL, tutor_comment = NULL, tutor_result = NULL,
                           submitted_at = datetime('now')
                       WHERE id = ?""",
                    (submission_id,),
                )
                conn.commit()
            else:
                cur = conn.execute(
                    "INSERT INTO student_submissions (assignment_id, student_id) VALUES (?, ?)",
                    (assignment_id, session["student_id"]),
                )
                submission_id = cur.lastrowid
                conn.commit()

            sub_dir = SUBMISSION_FILES_DIR / str(submission_id)
            sub_dir.mkdir(parents=True, exist_ok=True)
            saved_names = []
            for i, f in enumerate(files):
                safe = secure_filename(f.filename) or f"file_{i}"
                dest = sub_dir / f"{i:02d}_{safe}"
                f.save(dest)
                saved_names.append(dest.name)
            conn.execute(
                "UPDATE student_submissions SET files = ? WHERE id = ?", (json.dumps(saved_names), submission_id)
            )
            conn.commit()

            student = conn.execute("SELECT * FROM students WHERE id = ?", (session["student_id"],)).fetchone()
            task_file_names = json.loads(assignment["task_files"] or "[]")
            task_file_paths = [ASSIGNMENT_FILES_DIR / str(assignment_id) / n for n in task_file_names]

            notifications.notify_admin(
                "submission",
                f"{student['name']} submitted \"{assignment['title']}\"",
                link=url_for("admin.submission_detail", submission_id=submission_id),
            )

            conn.close()
            grading_jobs.start_grading_job(
                submission_id,
                [sub_dir / n for n in saved_names],
                student["name"],
                assignment["topic"],
                task_file_paths=task_file_paths,
            )
            return redirect(url_for("student.homework_detail", assignment_id=assignment_id))

    submission = conn.execute(
        "SELECT * FROM student_submissions WHERE assignment_id = ? AND student_id = ?",
        (assignment_id, session["student_id"]),
    ).fetchone()
    chat_rows = conn.execute(
        "SELECT role, content FROM hint_chat_messages WHERE assignment_id = ? AND student_id = ? ORDER BY id ASC",
        (assignment_id, session["student_id"]),
    ).fetchall()
    conn.close()

    task_files = json.loads(assignment["task_files"] or "[]")
    ai_result = json.loads(submission["ai_result"]) if submission and submission["ai_result"] else None
    tutor_result = json.loads(submission["tutor_result"]) if submission and submission["tutor_result"] else None
    problems = tutor_result if tutor_result is not None else (ai_result["problems"] if ai_result else [])

    return render_template(
        "student/homework_detail.html",
        assignment=assignment,
        submission=submission,
        problems=problems,
        task_files=task_files,
        chat_history=[dict(r) for r in chat_rows],
        errors=errors,
    )


@student_bp.route("/homeworks/<int:assignment_id>/remove", methods=["POST"])
@student_required
def remove_submission(assignment_id):
    conn = db.get_db()
    submission = conn.execute(
        "SELECT * FROM student_submissions WHERE assignment_id = ? AND student_id = ?",
        (assignment_id, session["student_id"]),
    ).fetchone()
    if not submission:
        conn.close()
        abort(404)
    if submission["feedback_published"]:
        conn.close()
        abort(403)

    submission_id = submission["id"]
    conn.execute("DELETE FROM student_submissions WHERE id = ?", (submission_id,))
    conn.commit()
    conn.close()
    shutil.rmtree(SUBMISSION_FILES_DIR / str(submission_id), ignore_errors=True)
    flash(t("homework.removed"))
    return redirect(url_for("student.homework_detail", assignment_id=assignment_id))


@student_bp.route("/homeworks/<int:assignment_id>/chat", methods=["POST"])
@student_required
def homework_chat_endpoint(assignment_id):
    conn = db.get_db()
    assignment = conn.execute(
        "SELECT * FROM homework_assignments WHERE id = ? AND student_id = ?",
        (assignment_id, session["student_id"]),
    ).fetchone()
    if not assignment:
        conn.close()
        abort(404)

    message = ((request.get_json(silent=True) or {}).get("message") or "").strip()
    if not message:
        conn.close()
        return jsonify({"error": "Empty message"}), 400

    rows = conn.execute(
        "SELECT role, content FROM hint_chat_messages WHERE assignment_id = ? AND student_id = ? ORDER BY id ASC",
        (assignment_id, session["student_id"]),
    ).fetchall()
    history = [dict(r) for r in rows]
    history.append({"role": "user", "content": message})

    student = conn.execute("SELECT * FROM students WHERE id = ?", (session["student_id"],)).fetchone()
    task_file_names = json.loads(assignment["task_files"] or "[]")
    task_file_paths = [ASSIGNMENT_FILES_DIR / str(assignment_id) / n for n in task_file_names]

    conn.execute(
        "INSERT INTO hint_chat_messages (assignment_id, student_id, role, content) VALUES (?, ?, 'user', ?)",
        (assignment_id, session["student_id"], message),
    )
    conn.commit()

    try:
        reply_text = homework_chat.reply(task_file_paths, history, lang=student["language"])
    except homework_chat.ChatError as exc:
        conn.close()
        return jsonify({"error": str(exc)}), 502

    conn.execute(
        "INSERT INTO hint_chat_messages (assignment_id, student_id, role, content) VALUES (?, ?, 'assistant', ?)",
        (assignment_id, session["student_id"], reply_text),
    )
    conn.commit()
    conn.close()

    return jsonify({"reply": reply_text})


@student_bp.route("/performance")
@student_required
def performance_view():
    conn = db.get_db()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (session["student_id"],)).fetchone()
    history = conn.execute(
        """SELECT ss.*, ha.title AS assignment_title
           FROM student_submissions ss
           JOIN homework_assignments ha ON ha.id = ss.assignment_id
           WHERE ss.student_id = ? AND ss.feedback_published = 1
           ORDER BY ss.reviewed_at DESC""",
        (session["student_id"],),
    ).fetchall()
    conn.close()
    grades = [r["tutor_grade"] for r in history]
    letter, gpa = performance.compute_average(grades)
    return render_template("student/performance.html", student=student, history=history, letter=letter, gpa=gpa)


@student_bp.route("/change-password", methods=["GET", "POST"])
@student_required
def change_password():
    error = None
    success = False
    if request.method == "POST":
        current = request.form.get("current_password", "")
        new = request.form.get("new_password", "")
        confirm = request.form.get("confirm_password", "")
        conn = db.get_db()
        student = conn.execute("SELECT * FROM students WHERE id = ?", (session["student_id"],)).fetchone()
        if not check_password(student["password_hash"], current):
            error = t("change_password.wrong_current")
        elif not new or new != confirm:
            error = t("change_password.mismatch")
        elif password_error(new, student["username"]):
            error = t("change_password.weak")
        else:
            conn.execute(
                "UPDATE students SET password_hash = ? WHERE id = ?", (hash_password(new), session["student_id"])
            )
            conn.commit()
            success = True
        conn.close()
    return render_template("student/change_password.html", error=error, success=success)


# ---- Notifications ----------------------------------------------------

@student_bp.route("/notifications/<int:notification_id>/open")
@student_required
def notification_open(notification_id):
    conn = db.get_db()
    notif = conn.execute(
        "SELECT * FROM notifications WHERE id = ? AND recipient_type = 'student' AND recipient_id = ?",
        (notification_id, session["student_id"]),
    ).fetchone()
    if notif:
        conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
        conn.commit()
    conn.close()
    return redirect(notif["link"] if notif and notif["link"] else url_for("student.dashboard"))


@student_bp.route("/notifications/mark-all-read", methods=["POST"])
@student_required
def notifications_mark_all_read():
    notifications.mark_all_read_student(session["student_id"])
    return redirect(request.referrer or url_for("student.dashboard"))


# ---- File serving (scoped to the logged-in student) -----------------------

@student_bp.route("/homeworks/<int:assignment_id>/task-files/<path:filename>")
@student_required
def task_file(assignment_id, filename):
    conn = db.get_db()
    assignment = conn.execute(
        "SELECT id FROM homework_assignments WHERE id = ? AND student_id = ?",
        (assignment_id, session["student_id"]),
    ).fetchone()
    conn.close()
    if not assignment:
        abort(404)
    return send_from_directory(ASSIGNMENT_FILES_DIR / str(assignment_id), filename)


@student_bp.route("/submissions/<int:submission_id>/files/<path:filename>")
@student_required
def submission_file(submission_id, filename):
    conn = db.get_db()
    submission = conn.execute(
        "SELECT id FROM student_submissions WHERE id = ? AND student_id = ?",
        (submission_id, session["student_id"]),
    ).fetchone()
    conn.close()
    if not submission:
        abort(404)
    return send_from_directory(SUBMISSION_FILES_DIR / str(submission_id), filename)
