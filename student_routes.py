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
import demo
import grading_jobs
import homework_chat
import notifications
import performance
import translations
from auth import (
    check_password,
    clear_failed_logins,
    hash_password,
    login_blocked,
    password_error,
    record_failed_login,
    safe_next_url,
    student_required,
)
from config import ALLOWED_EXT, ASSIGNMENT_FILES_DIR, MAX_FILES, SOLUTION_FILES_DIR, SUBMISSION_FILES_DIR
from translations import t

student_bp = Blueprint("student", __name__, url_prefix="/me")

# What a guest may POST: switching the language, logging in for real, and asking
# the hint helper (answered with demo.py's examples, nothing stored).
_GUEST_POSTS = {"student.set_language", "student.login", "student.homework_chat_endpoint"}


@student_bp.before_request
def keep_guests_read_only():
    if demo.is_guest() and request.method == "POST" and request.endpoint not in _GUEST_POSTS:
        flash(t("demo.read_only"))
        return redirect(request.referrer or url_for("student.dashboard"))
    return None


def _viewer():
    """(database, student id) for whoever is looking. A guest gets the demo
    database and its made-up student - never the real database."""
    if demo.is_guest():
        return demo.get_db(), demo.student_id()
    return db.get_db(), session["student_id"]


@student_bp.route("/demo")
def guest_login():
    """Look around the student area as a guest - from the login page or a link on
    tutorilya.com (?lang=ru). A logged-in student stays logged in as themselves."""
    if session.get("student_id"):
        return redirect(url_for("student.dashboard"))
    session["guest"] = True
    if request.args.get("lang") in ("en", "ru"):
        session["lang"] = request.args["lang"]
    return redirect(url_for("student.dashboard"))


@student_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        if login_blocked("student"):
            return render_template("student/login.html", error=t("login.too_many")), 429
        username = (request.form.get("username") or "").strip().lower()
        password = request.form.get("password", "")
        conn = db.get_db()
        student = conn.execute("SELECT * FROM students WHERE username = ?", (username,)).fetchone()
        if student and check_password(student["password_hash"], password):
            clear_failed_logins("student")
            session.pop("guest", None)
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
            return redirect(safe_next_url(request.args.get("next"), url_for("student.dashboard")))
        conn.close()
        record_failed_login("student")
        error = t("login.error")
    return render_template("student/login.html", error=error)


@student_bp.route("/logout")
def logout():
    session.pop("student_id", None)
    session.pop("guest", None)
    return redirect(url_for("student.login"))


@student_bp.route("/language/<lang>", methods=["POST"])
def set_language(lang):
    if lang not in ("en", "ru"):
        abort(400)
    session["lang"] = lang
    if session.get("student_id"):
        conn = db.get_db()
        student = conn.execute("SELECT * FROM students WHERE id = ?", (session["student_id"],)).fetchone()
        conn.execute("UPDATE students SET language = ? WHERE id = ?", (lang, session["student_id"]))
        conn.commit()
        conn.close()
        if student["language"] != lang and student["performance_narrative"]:
            performance.refresh_narrative_in_background(session["student_id"])
    return redirect(request.referrer or url_for("student.dashboard"))


def _homework_items(conn, student_id):
    """This student's assignments, newest first, each with its status
    (not_submitted / awaiting / reviewed) and, once reviewed, grade and comment."""
    assignments = conn.execute(
        "SELECT * FROM homework_assignments WHERE student_id = ? ORDER BY created_at DESC", (student_id,),
    ).fetchall()
    submissions = conn.execute(
        """SELECT assignment_id, feedback_published, tutor_grade, tutor_comment, submitted_at, reviewed_at, files
           FROM student_submissions WHERE student_id = ?""",
        (student_id,),
    ).fetchall()
    by_assignment = {}
    for s in submissions:
        by_assignment.setdefault(s["assignment_id"], []).append(s)
    items = []
    for a in assignments:
        subs = by_assignment.get(a["id"], [])
        published = next((s for s in subs if s["feedback_published"]), None)
        latest = published or (subs[-1] if subs else None)
        status = "reviewed" if published else ("awaiting" if subs else "not_submitted")
        items.append({
            "assignment": a,
            "status": status,
            "grade": published["tutor_grade"] if published else None,
            "comment": published["tutor_comment"] if published else None,
            "submitted_at": latest["submitted_at"] if latest else None,
            "reviewed_at": published["reviewed_at"] if published else None,
            "photo_count": len(json.loads(latest["files"] or "[]")) if latest else 0,
        })
    return items


@student_bp.route("/")
@student_required
def dashboard():
    conn, student_id = _viewer()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    items = _homework_items(conn, student_id)
    conn.close()
    columns = {status: [i for i in items if i["status"] == status]
               for status in ("not_submitted", "awaiting", "reviewed")}
    # oldest first, so the chart reads left to right like time
    recent = sorted((i for i in items if i["reviewed_at"]), key=lambda i: i["reviewed_at"])[-6:]
    letter, gpa = performance.compute_average([i["grade"] for i in items if i["grade"]])
    return render_template("student/dashboard.html", student=student, columns=columns,
                           recent_grades=recent, letter=letter, gpa=gpa, hint_limit=homework_chat.HINT_LIMIT)


@student_bp.route("/homeworks")
@student_required
def homeworks():
    conn, student_id = _viewer()
    items = _homework_items(conn, student_id)
    conn.close()
    return render_template("student/homeworks.html", items=items)


@student_bp.route("/homeworks/<int:assignment_id>", methods=["GET", "POST"])
@student_required
def homework_detail(assignment_id):
    conn, student_id = _viewer()
    assignment = conn.execute(
        "SELECT * FROM homework_assignments WHERE id = ? AND student_id = ?",
        (assignment_id, student_id),
    ).fetchone()
    if not assignment:
        conn.close()
        abort(404)

    existing = conn.execute(
        "SELECT * FROM student_submissions WHERE assignment_id = ? AND student_id = ?",
        (assignment_id, student_id),
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
            solution_file_names = json.loads(assignment["solution_files"] or "[]")
            solution_file_paths = [SOLUTION_FILES_DIR / str(assignment_id) / n for n in solution_file_names]

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
                assignment["topic"] or assignment["title"],
                task_file_paths=task_file_paths,
                solution_file_paths=solution_file_paths,
                curriculum=student["curriculum"],
                language=student["language"],
            )
            return redirect(url_for("student.homework_detail", assignment_id=assignment_id))

    submission = conn.execute(
        "SELECT * FROM student_submissions WHERE assignment_id = ? AND student_id = ?",
        (assignment_id, student_id),
    ).fetchone()
    chat_rows = conn.execute(
        "SELECT role, content FROM hint_chat_messages WHERE assignment_id = ? AND student_id = ? ORDER BY id ASC",
        (assignment_id, student_id),
    ).fetchall()
    conn.close()

    task_files = json.loads(assignment["task_files"] or "[]")
    ai_result = json.loads(submission["ai_result"]) if submission and submission["ai_result"] else None
    tutor_result = json.loads(submission["tutor_result"]) if submission and submission["tutor_result"] else None
    problems = tutor_result if tutor_result is not None else (ai_result["problems"] if ai_result else [])
    hints_used = sum(1 for r in chat_rows if r["role"] == "user")

    return render_template(
        "student/homework_detail.html",
        assignment=assignment,
        submission=submission,
        problems=problems,
        task_files=task_files,
        chat_history=[dict(r) for r in chat_rows],
        hint_remaining=max(0, homework_chat.HINT_LIMIT - hints_used),
        hint_limit=homework_chat.HINT_LIMIT,
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
    if demo.is_guest():
        data = request.get_json(silent=True) or {}
        try:
            return jsonify(demo.hint_reply(assignment_id, data.get("action"), data.get("task_number"),
                                           translations.current_lang()))
        except LookupError:
            abort(404)
        except ValueError:
            return jsonify({"error": "Invalid request"}), 400

    conn = db.get_db()
    assignment = conn.execute(
        "SELECT * FROM homework_assignments WHERE id = ? AND student_id = ?",
        (assignment_id, session["student_id"]),
    ).fetchone()
    if not assignment:
        conn.close()
        abort(404)

    rows = conn.execute(
        "SELECT role, content FROM hint_chat_messages WHERE assignment_id = ? AND student_id = ? ORDER BY id ASC",
        (assignment_id, session["student_id"]),
    ).fetchall()
    hints_used = sum(1 for r in rows if r["role"] == "user")
    if hints_used >= homework_chat.HINT_LIMIT:
        conn.close()
        return jsonify({"error": t("chat.limit_reached")}), 403

    student = conn.execute("SELECT * FROM students WHERE id = ?", (session["student_id"],)).fetchone()
    data = request.get_json(silent=True) or {}
    try:
        message = homework_chat.build_user_message(
            data.get("action"), data.get("task_number"), lang=student["language"]
        )
    except ValueError:
        conn.close()
        return jsonify({"error": "Invalid request"}), 400

    history = [dict(r) for r in rows]
    history.append({"role": "user", "content": message})

    task_file_names = json.loads(assignment["task_files"] or "[]")
    task_file_paths = [ASSIGNMENT_FILES_DIR / str(assignment_id) / n for n in task_file_names]

    # Inserting the question first reserves the coin, so two quick clicks can't both
    # pass the limit check above; if the model call fails the reservation is undone.
    cur = conn.execute(
        "INSERT INTO hint_chat_messages (assignment_id, student_id, role, content) VALUES (?, ?, 'user', ?)",
        (assignment_id, session["student_id"], message),
    )
    question_id = cur.lastrowid
    conn.commit()

    try:
        reply_text = homework_chat.reply(history, student=student, assignment=assignment,
                                         task_file_paths=task_file_paths)
    except homework_chat.ChatError:
        conn.execute("DELETE FROM hint_chat_messages WHERE id = ?", (question_id,))
        conn.commit()
        conn.close()
        return jsonify({"error": t("chat.failed")}), 502

    conn.execute(
        "INSERT INTO hint_chat_messages (assignment_id, student_id, role, content) VALUES (?, ?, 'assistant', ?)",
        (assignment_id, session["student_id"], reply_text),
    )
    conn.commit()
    conn.close()

    return jsonify({
        "reply": reply_text,
        "message": message,
        "remaining": homework_chat.HINT_LIMIT - (hints_used + 1),
    })


@student_bp.route("/performance")
@student_required
def performance_view():
    conn, student_id = _viewer()
    student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
    record = performance.homework_record(conn, student_id)
    conn.close()
    return render_template("student/performance.html", student=student, history=record["graded"],
                           missed=record["missed"], handed_in=record["handed_in"], due=record["due"],
                           letter=record["letter"], gpa=record["gpa"])


@student_bp.route("/change-password", methods=["GET", "POST"])
@student_required
def change_password():
    if demo.is_guest():
        return redirect(url_for("student.dashboard"))
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
    conn, student_id = _viewer()
    notif = conn.execute(
        "SELECT * FROM notifications WHERE id = ? AND recipient_type = 'student' AND recipient_id = ?",
        (notification_id, student_id),
    ).fetchone()
    if notif and not demo.is_guest():
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
    conn, student_id = _viewer()
    assignment = conn.execute(
        "SELECT id, task_files FROM homework_assignments WHERE id = ? AND student_id = ?",
        (assignment_id, student_id),
    ).fetchone()
    conn.close()
    if not assignment or filename not in json.loads(assignment["task_files"] or "[]"):
        abort(404)
    base = demo.SHEETS_DIR if demo.is_guest() else ASSIGNMENT_FILES_DIR
    return send_from_directory(base / str(assignment_id), filename)


@student_bp.route("/submissions/<int:submission_id>/files/<path:filename>")
@student_required
def submission_file(submission_id, filename):
    if demo.is_guest():
        abort(404)  # the demo shows no student photos
    conn = db.get_db()
    submission = conn.execute(
        "SELECT id, files FROM student_submissions WHERE id = ? AND student_id = ?",
        (submission_id, session["student_id"]),
    ).fetchone()
    conn.close()
    if not submission or filename not in json.loads(submission["files"] or "[]"):
        abort(404)
    return send_from_directory(SUBMISSION_FILES_DIR / str(submission_id), filename)
