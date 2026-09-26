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
import notifications
import performance
import translations
import performance_pdf
from auth import (
    admin_required,
    clear_failed_logins,
    hash_password,
    login_blocked,
    password_error,
    record_failed_login,
    safe_next_url,
)
from config import (
    ALLOWED_EXT,
    ASSIGNMENT_FILES_DIR,
    CURRICULA,
    MAX_FILES,
    SOLUTION_FILES_DIR,
    SUBMISSION_FILES_DIR,
)

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")


def generate_temp_password():
    return secrets.token_urlsafe(6)


@admin_bp.route("/login", methods=["GET", "POST"])
def admin_login():
    error = None
    if request.method == "POST":
        if login_blocked("admin"):
            return render_template(
                "admin/login.html", error="Too many failed attempts. Wait 15 minutes and try again."
            ), 429
        password = request.form.get("password", "")
        expected = os.environ.get("ADMIN_PASSWORD")
        if not expected:
            error = "ADMIN_PASSWORD is not set on the server - check .env."
        elif secrets.compare_digest(password, expected):
            clear_failed_logins("admin")
            session["is_admin"] = True
            return redirect(safe_next_url(request.args.get("next"), url_for("admin.dashboard")))
        else:
            record_failed_login("admin")
            error = "Wrong password."
    return render_template("admin/login.html", error=error)


@admin_bp.route("/logout")
def admin_logout():
    session.pop("is_admin", None)
    return redirect(url_for("admin.admin_login"))


@admin_bp.route("")
@admin_required
def dashboard():
    status = request.args.get("status", "new")
    if status not in ("new", "graded", "all"):
        status = "new"

    where = ""
    if status == "new":
        where = "WHERE ss.feedback_published = 0"
    elif status == "graded":
        where = "WHERE ss.feedback_published = 1"

    conn = db.get_db()
    submissions = conn.execute(
        f"""SELECT ss.*, s.name AS student_name, ha.title AS assignment_title
           FROM student_submissions ss
           JOIN students s ON s.id = ss.student_id
           JOIN homework_assignments ha ON ha.id = ss.assignment_id
           {where}
           ORDER BY ss.submitted_at DESC LIMIT 200"""
    ).fetchall()
    new_count = conn.execute("SELECT COUNT(*) AS c FROM student_submissions WHERE feedback_published = 0").fetchone()["c"]
    graded_count = conn.execute("SELECT COUNT(*) AS c FROM student_submissions WHERE feedback_published = 1").fetchone()["c"]
    conn.close()
    return render_template(
        "admin/dashboard.html",
        submissions=submissions,
        status=status,
        new_count=new_count,
        graded_count=graded_count,
    )


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
            profile = _profile_from_form()
            try:
                conn.execute(
                    """INSERT INTO students
                       (name, username, password_hash, schedule_text, miro_link, zoom_link,
                        language, curriculum, school_year, tutor_notes)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (name, username, hash_password(password), schedule_text, miro_link, zoom_link,
                     profile["language"], profile["curriculum"], profile["school_year"], profile["tutor_notes"]),
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
    name = (request.form.get("name") or "").strip()
    if not name:
        flash("Name can't be empty.")
        return redirect(url_for("admin.student_detail", student_id=student_id))
    profile = _profile_from_form()
    conn = db.get_db()
    conn.execute(
        """UPDATE students SET name = ?, schedule_text = ?, miro_link = ?, zoom_link = ?,
               language = ?, curriculum = ?, school_year = ?, tutor_notes = ?
           WHERE id = ?""",
        (
            name,
            (request.form.get("schedule_text") or "").strip(),
            (request.form.get("miro_link") or "").strip(),
            (request.form.get("zoom_link") or "").strip(),
            profile["language"], profile["curriculum"], profile["school_year"], profile["tutor_notes"],
            student_id,
        ),
    )
    conn.commit()
    conn.close()
    flash("Student info updated.")
    return redirect(url_for("admin.student_detail", student_id=student_id))


def _profile_from_form():
    """The fields that shape how the AI talks to and grades this student."""
    language = request.form.get("language")
    curriculum = request.form.get("curriculum")
    return {
        "language": language if language in ("en", "ru") else "en",
        "curriculum": curriculum if curriculum in CURRICULA else "other",
        "school_year": (request.form.get("school_year") or "").strip() or None,
        "tutor_notes": (request.form.get("tutor_notes") or "").strip() or None,
    }


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
        shutil.rmtree(SOLUTION_FILES_DIR / str(assignment_id), ignore_errors=True)
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
    solution_files = [f for f in request.files.getlist("solution_files") if f and f.filename]

    errors = []
    if not title:
        errors.append("Title is required.")
    for f in task_files + solution_files:
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

    if solution_files:
        solution_dir = SOLUTION_FILES_DIR / str(assignment_id)
        solution_dir.mkdir(parents=True, exist_ok=True)
        saved_names = []
        for i, f in enumerate(solution_files):
            safe = secure_filename(f.filename) or f"file_{i}"
            dest = solution_dir / f"{i:02d}_{safe}"
            f.save(dest)
            saved_names.append(dest.name)
        conn.execute(
            "UPDATE homework_assignments SET solution_files = ? WHERE id = ?",
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
    if not task_files:
        flash("No homework sheet attached - AI grading will have to guess which problems exist. "
              "Delete and recreate the assignment with the sheet if you have it.")
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
    shutil.rmtree(SOLUTION_FILES_DIR / str(assignment_id), ignore_errors=True)


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

        problem_count = int(request.form.get("problem_count", 0) or 0)
        if problem_count:
            edited_problems = []
            for i in range(problem_count):
                edited_problems.append({
                    "problem_label": request.form.get(f"problem_label_{i}", ""),
                    "problem_text": request.form.get(f"problem_text_{i}", ""),
                    "student_answer": (request.form.get(f"student_answer_{i}") or "").strip(),
                    "work": request.form.get(f"work_{i}", ""),
                    "correct_answer": (request.form.get(f"correct_answer_{i}") or "").strip(),
                    "verdict": request.form.get(f"verdict_{i}", "unclear"),
                    "explanation": (request.form.get(f"explanation_{i}") or "").strip(),
                    "confidence": request.form.get(f"confidence_{i}", ""),
                })
            conn.execute(
                "UPDATE student_submissions SET tutor_result = ? WHERE id = ?",
                (json.dumps(edited_problems), submission_id),
            )
            conn.commit()

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
                performance.refresh_narrative_in_background(submission["student_id"])
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
    tutor_result = json.loads(submission["tutor_result"]) if submission["tutor_result"] else None
    problems = tutor_result if tutor_result is not None else (ai_result["problems"] if ai_result else [])
    show_form = not submission["feedback_published"] or request.args.get("edit") == "1"

    return render_template(
        "admin/submission_detail.html",
        submission=submission,
        assignment=assignment,
        student=student,
        files=files,
        task_files=task_files,
        ai_result=ai_result,
        problems=problems,
        show_form=show_form,
    )


@admin_bp.route("/submissions/<int:submission_id>/status")
@admin_required
def submission_status(submission_id):
    conn = db.get_db()
    row = conn.execute("SELECT ai_status FROM student_submissions WHERE id = ?", (submission_id,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    return jsonify(status=row["ai_status"])


@admin_bp.route("/submissions/<int:submission_id>/delete", methods=["POST"])
@admin_required
def delete_submission(submission_id):
    conn = db.get_db()
    submission = conn.execute("SELECT * FROM student_submissions WHERE id = ?", (submission_id,)).fetchone()
    if not submission:
        conn.close()
        abort(404)
    conn.execute("DELETE FROM student_submissions WHERE id = ?", (submission_id,))
    conn.commit()
    conn.close()
    shutil.rmtree(SUBMISSION_FILES_DIR / str(submission_id), ignore_errors=True)
    flash("Submission deleted.")
    return redirect(url_for("admin.dashboard"))


def _tutor_corrected_answers(submission):
    """Student answers the tutor changed by hand. A recheck keeps these instead of
    re-reading the photo, so it can't undo the tutor's own corrections."""
    if not submission["tutor_result"] or not submission["ai_result"]:
        return {}
    ai_answers = {p["problem_label"]: p["student_answer"] for p in json.loads(submission["ai_result"])["problems"]}
    return {
        p["problem_label"]: p["student_answer"]
        for p in json.loads(submission["tutor_result"])
        if p["student_answer"] != ai_answers.get(p["problem_label"])
    }


def _start_grading(conn, submission, tutor_note=None, reset_tutor_result=False):
    assignment = conn.execute(
        "SELECT * FROM homework_assignments WHERE id = ?", (submission["assignment_id"],)
    ).fetchone()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (submission["student_id"],)).fetchone()

    files = json.loads(submission["files"] or "[]")
    sub_dir = SUBMISSION_FILES_DIR / str(submission["id"])
    task_file_names = json.loads(assignment["task_files"] or "[]") if assignment else []
    task_file_paths = [ASSIGNMENT_FILES_DIR / str(submission["assignment_id"]) / n for n in task_file_names]
    solution_file_names = json.loads(assignment["solution_files"] or "[]") if assignment else []
    solution_file_paths = [SOLUTION_FILES_DIR / str(submission["assignment_id"]) / n for n in solution_file_names]

    grading_jobs.start_grading_job(
        submission["id"],
        [sub_dir / n for n in files],
        student["name"],
        (assignment["topic"] or assignment["title"]) if assignment else None,
        task_file_paths=task_file_paths,
        solution_file_paths=solution_file_paths,
        tutor_note=tutor_note,
        reset_tutor_result=reset_tutor_result,
        curriculum=student["curriculum"],
        language=student["language"],
        known_answers=_tutor_corrected_answers(submission),
    )


@admin_bp.route("/submissions/<int:submission_id>/regrade", methods=["POST"])
@admin_required
def regrade_submission(submission_id):
    conn = db.get_db()
    submission = conn.execute("SELECT * FROM student_submissions WHERE id = ?", (submission_id,)).fetchone()
    if not submission:
        conn.close()
        abort(404)

    problem_count = int(request.form.get("problem_count", 0) or 0)
    notes = []
    for i in range(problem_count):
        note = (request.form.get(f"ai_note_{i}") or "").strip()
        if note:
            label = request.form.get(f"problem_label_{i}") or f"#{i + 1}"
            notes.append(f"Problem {label}: {note}")
    tutor_note = "\n".join(notes)
    if not tutor_note:
        conn.close()
        flash("Add a note on at least one task before asking for a recheck.")
        return redirect(url_for("admin.submission_detail", submission_id=submission_id))

    _start_grading(conn, submission, tutor_note=tutor_note, reset_tutor_result=True)
    conn.close()
    flash("AI is rechecking the submission in the background - this page will update automatically when it's done.")
    return redirect(url_for("admin.submission_detail", submission_id=submission_id))


@admin_bp.route("/submissions/<int:submission_id>/retry", methods=["POST"])
@admin_required
def retry_grading(submission_id):
    conn = db.get_db()
    submission = conn.execute("SELECT * FROM student_submissions WHERE id = ?", (submission_id,)).fetchone()
    if not submission:
        conn.close()
        abort(404)

    _start_grading(conn, submission)
    conn.close()
    flash("Retrying AI grading in the background - this page will update automatically when it's done.")
    return redirect(url_for("admin.submission_detail", submission_id=submission_id))


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

def _serve_listed_file(table, column, row_id, directory, filename):
    """Serve a file only if the database lists it for that row - never anything
    else that happens to sit in the directory."""
    conn = db.get_db()
    row = conn.execute(f"SELECT {column} FROM {table} WHERE id = ?", (row_id,)).fetchone()
    conn.close()
    if not row or filename not in json.loads(row[column] or "[]"):
        abort(404)
    return send_from_directory(directory / str(row_id), filename)


@admin_bp.route("/assignment-files/<int:assignment_id>/<path:filename>")
@admin_required
def assignment_file(assignment_id, filename):
    return _serve_listed_file("homework_assignments", "task_files", assignment_id, ASSIGNMENT_FILES_DIR, filename)


@admin_bp.route("/assignment-solutions/<int:assignment_id>/<path:filename>")
@admin_required
def assignment_solution_file(assignment_id, filename):
    return _serve_listed_file("homework_assignments", "solution_files", assignment_id, SOLUTION_FILES_DIR, filename)


@admin_bp.route("/submission-files/<int:submission_id>/<path:filename>")
@admin_required
def submission_file(submission_id, filename):
    return _serve_listed_file("student_submissions", "files", submission_id, SUBMISSION_FILES_DIR, filename)
