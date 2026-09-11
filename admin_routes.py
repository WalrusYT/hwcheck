"""Tutor-facing admin area: manage students, assignments, and review/grade submissions."""

import json
import os
import secrets
import shutil
import sqlite3
from pathlib import Path

from flask import (
    Blueprint,
    Response,
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

import db
import notifications
import performance
import translations
import performance_pdf
from auth import admin_required, hash_password, password_error
from config import ALLOWED_EXT, ASSIGNMENT_FILES_DIR, MAX_FILES, SUBMISSION_FILES_DIR

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def generate_temp_password():
    return secrets.token_urlsafe(6)


@admin_bp.route("/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        password = request.form.get("password", "")
        expected = os.environ.get("ADMIN_PASSWORD")
        if not expected:
            error = "ADMIN_PASSWORD is not set on the server - check .env."
        elif secrets.compare_digest(password, expected):
            session["is_admin"] = True
            return redirect(request.args.get("next") or url_for("admin.dashboard"))
        else:
            error = "Wrong password."
    return render_template("admin/login.html", error=error)


@admin_bp.route("/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin.admin_login"))


@admin_bp.route("")
@admin_required
def dashboard():
    conn = db.get_db()
    submissions = conn.execute(
        """SELECT ss.*, s.name AS student_name, ha.title AS assignment_title
           FROM student_submissions ss
           JOIN students s ON s.id = ss.student_id
           JOIN homework_assignments ha ON ha.id = ss.assignment_id
           ORDER BY ss.submitted_at DESC LIMIT 200"""
    ).fetchall()
    conn.close()
    return render_template("admin/dashboard.html", submissions=submissions)


# ---- Students --------------------------------------------------------------

@admin_bp.route("/students", methods=["GET", "POST"])
@admin_required
def students():
    conn = db.get_db()
    suggested_password = generate_temp_password()
    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password") or suggested_password
        schedule_text = (request.form.get("schedule_text") or "").strip()
        miro_link = (request.form.get("miro_link") or "").strip()
        zoom_link = (request.form.get("zoom_link") or "").strip()

        pw_error = password_error(password, username)
        if not name or not username:
            flash("Name and username are required.")
        elif pw_error:
            flash(pw_error)
        else:
            try:
                conn.execute(
                    """INSERT INTO students
                       (name, username, password_hash, schedule_text, miro_link, zoom_link)
                       VALUES (?, ?, ?, ?, ?, ?)""",
                    (name, username, hash_password(password), schedule_text, miro_link, zoom_link),
                )
                conn.commit()
                flash(f"Created student '{name}' (username: {username}, password: {password}) - share these with them.")
            except sqlite3.IntegrityError:
                flash(f"Username '{username}' is already taken.")
    rows = conn.execute("SELECT * FROM students ORDER BY created_at DESC").fetchall()
    conn.close()
    return render_template("admin/students.html", students=rows, suggested_password=suggested_password)


@admin_bp.route("/students/<int:student_id>", methods=["GET"])
@admin_required
def student_detail(student_id):
    conn = db.get_db()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        abort(404)
    assignments = conn.execute(
        "SELECT * FROM homework_assignments WHERE student_id = ? ORDER BY created_at DESC",
        (student_id,),
    ).fetchall()
    conn.close()
    return render_template("admin/student_detail.html", student=student, assignments=assignments)


@admin_bp.route("/students/<int:student_id>/update", methods=["POST"])
@admin_required
def student_update(student_id):
    conn = db.get_db()
    conn.execute(
        """UPDATE students SET name = ?, schedule_text = ?, miro_link = ?, zoom_link = ? WHERE id = ?""",
        (
            (request.form.get("name") or "").strip(),
            (request.form.get("schedule_text") or "").strip(),
            (request.form.get("miro_link") or "").strip(),
            (request.form.get("zoom_link") or "").strip(),
            student_id,
        ),
    )
    conn.commit()
    conn.close()
    flash("Student info updated.")
    return redirect(url_for("admin.student_detail", student_id=student_id))


@admin_bp.route("/students/<int:student_id>/reset-password", methods=["POST"])
@admin_required
def student_reset_password(student_id):
    new_password = generate_temp_password()
    conn = db.get_db()
    conn.execute("UPDATE students SET password_hash = ? WHERE id = ?", (hash_password(new_password), student_id))
    conn.commit()
    conn.close()
    flash(f"New password: {new_password} - share this with the student.")
    return redirect(url_for("admin.student_detail", student_id=student_id))


def _delete_student_cascade(conn, student_id):
    """Delete a student and everything that references them: assignments,
    submissions, chat history, notifications - plus their uploaded files on disk."""
    assignment_ids = [
        r["id"] for r in conn.execute(
            "SELECT id FROM homework_assignments WHERE student_id = ?", (student_id,)
        )
    ]
    submission_ids = [
        r["id"] for r in conn.execute(
            "SELECT id FROM student_submissions WHERE student_id = ?", (student_id,)
        )
    ]

    conn.execute("DELETE FROM hint_chat_messages WHERE student_id = ?", (student_id,))
    conn.execute(
        "DELETE FROM notifications WHERE recipient_type = 'student' AND recipient_id = ?", (student_id,)
    )
    conn.execute("DELETE FROM student_submissions WHERE student_id = ?", (student_id,))
    conn.execute("DELETE FROM homework_assignments WHERE student_id = ?", (student_id,))
    conn.execute("DELETE FROM students WHERE id = ?", (student_id,))
    conn.commit()

    for assignment_id in assignment_ids:
        shutil.rmtree(ASSIGNMENT_FILES_DIR / str(assignment_id), ignore_errors=True)
    for submission_id in submission_ids:
        shutil.rmtree(SUBMISSION_FILES_DIR / str(submission_id), ignore_errors=True)


@admin_bp.route("/students/<int:student_id>/delete", methods=["POST"])
@admin_required
def delete_student(student_id):
    conn = db.get_db()
    student = conn.execute("SELECT name FROM students WHERE id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        abort(404)
    name = student["name"]
    _delete_student_cascade(conn, student_id)
    conn.close()
    flash(f"Deleted student '{name}' and all their homework data.")
    return redirect(url_for("admin.students"))


@admin_bp.route("/students/<int:student_id>/assignments", methods=["POST"])
@admin_required
def create_assignment(student_id):
    conn = db.get_db()
    student = conn.execute("SELECT id, language FROM students WHERE id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        abort(404)

    title = (request.form.get("title") or "").strip()
    topic = (request.form.get("topic") or "").strip()
    task_files = [f for f in request.files.getlist("task_files") if f and f.filename]

    errors = []
    if not title:
        errors.append("Title is required.")
    for f in task_files:
        if Path(f.filename).suffix.lower() not in ALLOWED_EXT:
            errors.append(f"Unsupported file type: {f.filename}.")

    if errors:
        for e in errors:
            flash(e)
        conn.close()
        return redirect(url_for("admin.student_detail", student_id=student_id))

    cur = conn.execute(
        "INSERT INTO homework_assignments (student_id, title, topic) VALUES (?, ?, ?)",
        (student_id, title, topic),
    )
    assignment_id = cur.lastrowid
    conn.commit()

    if task_files:
        assignment_dir = ASSIGNMENT_FILES_DIR / str(assignment_id)
        assignment_dir.mkdir(parents=True, exist_ok=True)
        saved_names = []
        for i, f in enumerate(task_files):
            safe = secure_filename(f.filename) or f"file_{i}"
            dest = assignment_dir / f"{i:02d}_{safe}"
            f.save(dest)
            saved_names.append(dest.name)
        conn.execute(
            "UPDATE homework_assignments SET task_files = ? WHERE id = ?",
            (json.dumps(saved_names), assignment_id),
        )
        conn.commit()

    conn.close()
    notifications.notify_student(
        student_id,
        "new_assignment",
        translations.render("notif.new_assignment", student["language"], title=title),
        link=url_for("student.homework_detail", assignment_id=assignment_id),
    )
    flash(f"Created assignment '{title}'.")
    return redirect(url_for("admin.student_detail", student_id=student_id))


def _delete_assignment_cascade(conn, assignment_id):
    """Delete an assignment and everything that references it: submissions
    and chat history - plus files on disk for the assignment and its submissions."""
    submission_ids = [
        r["id"] for r in conn.execute(
            "SELECT id FROM student_submissions WHERE assignment_id = ?", (assignment_id,)
        )
    ]

    conn.execute("DELETE FROM hint_chat_messages WHERE assignment_id = ?", (assignment_id,))
    conn.execute("DELETE FROM student_submissions WHERE assignment_id = ?", (assignment_id,))
    conn.execute("DELETE FROM homework_assignments WHERE id = ?", (assignment_id,))
    conn.commit()

    for submission_id in submission_ids:
        shutil.rmtree(SUBMISSION_FILES_DIR / str(submission_id), ignore_errors=True)
    shutil.rmtree(ASSIGNMENT_FILES_DIR / str(assignment_id), ignore_errors=True)


@admin_bp.route("/assignments/<int:assignment_id>/delete", methods=["POST"])
@admin_required
def delete_assignment(assignment_id):
    conn = db.get_db()
    assignment = conn.execute(
        "SELECT title, student_id FROM homework_assignments WHERE id = ?", (assignment_id,)
    ).fetchone()
    if not assignment:
        conn.close()
        abort(404)
    student_id = assignment["student_id"]
    title = assignment["title"]
    _delete_assignment_cascade(conn, assignment_id)
    conn.close()
    flash(f"Deleted assignment '{title}'.")
    return redirect(url_for("admin.student_detail", student_id=student_id))


# ---- Performance -------------------------------------------------------

@admin_bp.route("/students/<int:student_id>/performance")
@admin_required
def student_performance(student_id):
    conn = db.get_db()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        abort(404)
    history = conn.execute(
        """SELECT ss.*, ha.title AS assignment_title
           FROM student_submissions ss
           JOIN homework_assignments ha ON ha.id = ss.assignment_id
           WHERE ss.student_id = ? AND ss.feedback_published = 1
           ORDER BY ss.reviewed_at DESC""",
        (student_id,),
    ).fetchall()
    conn.close()
    grades = [r["tutor_grade"] for r in history]
    letter, gpa = performance.compute_average(grades)
    return render_template(
        "admin/student_performance.html", student=student, history=history, letter=letter, gpa=gpa
    )


@admin_bp.route("/students/<int:student_id>/performance.pdf")
@admin_required
def student_performance_pdf(student_id):
    conn = db.get_db()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    if not student:
        conn.close()
        abort(404)
    history = conn.execute(
        """SELECT ss.*, ha.title AS assignment_title
           FROM student_submissions ss
           JOIN homework_assignments ha ON ha.id = ss.assignment_id
           WHERE ss.student_id = ? AND ss.feedback_published = 1
           ORDER BY ss.reviewed_at DESC""",
        (student_id,),
    ).fetchall()
    conn.close()

    grades = [r["tutor_grade"] for r in history]
    letter, gpa = performance.compute_average(grades)
    history_data = [
        {"title": r["assignment_title"], "submitted_at": r["reviewed_at"] or r["submitted_at"], "grade": r["tutor_grade"]}
        for r in history
    ]
    pdf_bytes = performance_pdf.build_performance_pdf(
        student["name"], letter, gpa, history_data, student["performance_narrative"]
    )
    filename = f"{secure_filename(student['name'])}_performance.pdf"
    return Response(
        pdf_bytes,
        mimetype="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


def _refresh_narrative(conn, student_id):
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    rows = conn.execute(
        """SELECT ss.tutor_grade, ss.tutor_comment, ha.title AS assignment_title
           FROM student_submissions ss
           JOIN homework_assignments ha ON ha.id = ss.assignment_id
           WHERE ss.student_id = ? AND ss.feedback_published = 1
           ORDER BY ss.reviewed_at DESC LIMIT 15""",
        (student_id,),
    ).fetchall()
    history = [{"title": r["assignment_title"], "grade": r["tutor_grade"], "comment": r["tutor_comment"]} for r in rows]
    try:
        narrative = performance.generate_narrative(student["name"], history, lang=student["language"])
    except Exception:
        narrative = student["performance_narrative"]
    conn.execute(
        "UPDATE students SET performance_narrative = ?, performance_narrative_updated_at = datetime('now') WHERE id = ?",
        (narrative, student_id),
    )


# ---- Submission review ---------------------------------------------------

@admin_bp.route("/submissions/<int:submission_id>", methods=["GET", "POST"])
@admin_required
def submission_detail(submission_id):
    conn = db.get_db()
    submission = conn.execute("SELECT * FROM student_submissions WHERE id = ?", (submission_id,)).fetchone()
    if not submission:
        conn.close()
        abort(404)

    if request.method == "POST":
        grade = (request.form.get("grade") or "").strip().upper()
        comment = request.form.get("tutor_comment", "")
        publish = request.form.get("action") == "publish"

        if publish and grade not in ("A", "B", "C", "D", "F"):
            flash("Pick a grade before publishing.")
        else:
            if publish:
                previous_grade = submission["tutor_grade"]
                conn.execute(
                    """UPDATE student_submissions
                       SET tutor_grade = ?, tutor_comment = ?, feedback_published = 1,
                           reviewed_at = datetime('now')
                       WHERE id = ?""",
                    (grade, comment, submission_id),
                )
                conn.commit()
                _refresh_narrative(conn, submission["student_id"])
                conn.commit()
                if grade != previous_grade:
                    assignment_title = conn.execute(
                        "SELECT title FROM homework_assignments WHERE id = ?", (submission["assignment_id"],)
                    ).fetchone()["title"]
                    student_lang = conn.execute(
                        "SELECT language FROM students WHERE id = ?", (submission["student_id"],)
                    ).fetchone()["language"]
                    notifications.notify_student(
                        submission["student_id"],
                        "feedback_published",
                        translations.render("notif.graded", student_lang, title=assignment_title, grade=grade),
                        link=url_for("student.homework_detail", assignment_id=submission["assignment_id"]),
                    )
                flash("Feedback published to student.")
            else:
                conn.execute(
                    "UPDATE student_submissions SET tutor_grade = ?, tutor_comment = ? WHERE id = ?",
                    (grade or None, comment, submission_id),
                )
                conn.commit()
                flash("Draft saved.")
        conn.close()
        return redirect(url_for("admin.submission_detail", submission_id=submission_id))

    assignment = conn.execute(
        "SELECT * FROM homework_assignments WHERE id = ?", (submission["assignment_id"],)
    ).fetchone()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (submission["student_id"],)).fetchone()
    conn.close()

    files = json.loads(submission["files"] or "[]")
    task_files = json.loads(assignment["task_files"] or "[]") if assignment else []
    ai_result = json.loads(submission["ai_result"]) if submission["ai_result"] else None
    show_form = not submission["feedback_published"] or request.args.get("edit") == "1"

    return render_template(
        "admin/submission_detail.html",
        submission=submission,
        assignment=assignment,
        student=student,
        files=files,
        task_files=task_files,
        ai_result=ai_result,
        show_form=show_form,
    )


# ---- Notifications ---------------------------------------------------------

@admin_bp.route("/notifications/<int:notification_id>/open")
@admin_required
def notification_open(notification_id):
    conn = db.get_db()
    notif = conn.execute(
        "SELECT * FROM notifications WHERE id = ? AND recipient_type = 'admin'", (notification_id,)
    ).fetchone()
    if notif:
        conn.execute("UPDATE notifications SET is_read = 1 WHERE id = ?", (notification_id,))
        conn.commit()
    conn.close()
    return redirect(notif["link"] if notif and notif["link"] else url_for("admin.dashboard"))


@admin_bp.route("/notifications/mark-all-read", methods=["POST"])
@admin_required
def notifications_mark_all_read():
    notifications.mark_all_read_admin()
    return redirect(request.referrer or url_for("admin.dashboard"))


# ---- File serving ---------------------------------------------------------

@admin_bp.route("/assignment-files/<int:assignment_id>/<path:filename>")
@admin_required
def assignment_file(assignment_id, filename):
    return send_from_directory(ASSIGNMENT_FILES_DIR / str(assignment_id), filename)


@admin_bp.route("/submission-files/<int:submission_id>/<path:filename>")
@admin_required
def submission_file(submission_id, filename):
    return send_from_directory(SUBMISSION_FILES_DIR / str(submission_id), filename)
