"""Runs AI grading on a background thread so a request never blocks on the
AI call - grading a multi-page submission can take well over a minute, longer
than gunicorn's worker timeout.

Jobs run in-process, so the app must run a single gunicorn worker (see
render.yaml): app.py's startup sweep marks every still-pending job as
interrupted, which would clobber live jobs belonging to another worker.
"""

import ctypes
import ctypes.util
import gc
import json
import logging
import sys
import threading
import uuid

import db
from grading import GradingError, grade_submission

log = logging.getLogger(__name__)

# Memory on the 512 MB Render instance (measured 2026-09-28): a grading holds a
# multi-photo request while it is sent, and glibc keeps a separate heap per thread
# and never shrinks it - one grading left the instance at 460 MB for a whole day,
# and the next one ran it out of memory. So on Linux: few heaps, hand freed memory
# back after every job, and grade one submission at a time (others wait their turn).
_libc = None
if sys.platform.startswith("linux"):
    try:
        _libc = ctypes.CDLL(ctypes.util.find_library("c") or "libc.so.6")
        _libc.mallopt(-8, 2)  # M_ARENA_MAX = 2
    except (OSError, AttributeError):
        _libc = None

_one_grading_at_a_time = threading.Lock()


def release_memory():
    gc.collect()
    if _libc is not None:
        try:
            _libc.malloc_trim(0)
        except AttributeError:  # not glibc
            pass


def _run_in_background(fn):
    threading.Thread(target=fn, daemon=True).start()


def start_grading_job(submission_id, file_paths, student_name, topic=None,
                      task_file_paths=None, solution_file_paths=None, tutor_note=None,
                      reset_tutor_result=False, curriculum="other", language="en", known_answers=None):
    # Each job gets an id; only the latest job for a submission may write its result.
    # Otherwise a student who resubmits while the previous grading is still running
    # gets the old photos' grade written over the new one when the slow job finishes.
    job_id = uuid.uuid4().hex
    conn = db.get_db()
    conn.execute(
        "UPDATE student_submissions SET ai_status = 'pending', ai_error = NULL, ai_job_id = ? WHERE id = ?",
        (job_id, submission_id),
    )
    conn.commit()
    conn.close()

    def finish(sql, params):
        conn = db.get_db()
        cur = conn.execute(sql + " WHERE id = ? AND ai_job_id = ?", (*params, submission_id, job_id))
        conn.commit()
        conn.close()
        if cur.rowcount == 0:
            log.info("grading job %s for submission %s superseded; result discarded", job_id, submission_id)

    def run():
        with _one_grading_at_a_time:
            try:
                result = grade_submission(
                    file_paths, student_name, topic,
                    task_file_paths=task_file_paths, solution_file_paths=solution_file_paths,
                    tutor_note=tutor_note, curriculum=curriculum, language=language, known_answers=known_answers,
                )
                reset = ", tutor_result = NULL" if reset_tutor_result else ""
                finish(f"UPDATE student_submissions SET ai_result = ?, ai_status = 'done', ai_error = NULL{reset}",
                       (json.dumps(result),))
            except GradingError as exc:
                finish("UPDATE student_submissions SET ai_status = 'error', ai_error = ?", (str(exc),))
            except Exception as exc:
                # A thread that dies silently would leave the submission stuck on "pending".
                log.exception("grading job %s crashed", job_id)
                finish("UPDATE student_submissions SET ai_status = 'error', ai_error = ?", (f"Unexpected error: {exc}",))
            finally:
                release_memory()

    _run_in_background(run)
    return job_id
