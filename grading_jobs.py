"""Runs AI grading on a background thread so a request never blocks on the
OpenAI call - grading a multi-image submission can take well over a minute,
which used to block the request handler long enough to trip gunicorn's
worker timeout and surface as a 500 to the tutor/student."""

import json
import threading

import db
from grading import GradingError, grade_submission


def start_grading_job(submission_id, file_paths, student_name, topic=None,
                       task_file_paths=None, tutor_note=None, reset_tutor_result=False):
    def run():
        try:
            result = grade_submission(
                file_paths, student_name, topic,
                task_file_paths=task_file_paths, tutor_note=tutor_note,
            )
            conn = db.get_db()
            if reset_tutor_result:
                conn.execute(
                    """UPDATE student_submissions
                       SET ai_result = ?, ai_status = 'done', ai_error = NULL, tutor_result = NULL
                       WHERE id = ?""",
                    (json.dumps(result), submission_id),
                )
            else:
                conn.execute(
                    "UPDATE student_submissions SET ai_result = ?, ai_status = 'done', ai_error = NULL WHERE id = ?",
                    (json.dumps(result), submission_id),
                )
            conn.commit()
            conn.close()
        except GradingError as exc:
            conn = db.get_db()
            conn.execute(
                "UPDATE student_submissions SET ai_status = 'error', ai_error = ? WHERE id = ?",
                (str(exc), submission_id),
            )
            conn.commit()
            conn.close()
        except Exception as exc:
            # A background thread that dies silently would leave the submission
            # stuck on "pending" forever with no way for the tutor to notice.
            conn = db.get_db()
            conn.execute(
                "UPDATE student_submissions SET ai_status = 'error', ai_error = ? WHERE id = ?",
                (f"Unexpected error: {exc}", submission_id),
            )
            conn.commit()
            conn.close()

    threading.Thread(target=run, daemon=True).start()
