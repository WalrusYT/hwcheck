"""The Render instance has 512 MB. Rechecking a 4-photo submission ran it out of memory
(2026-09-28): gunicorn's master held a second copy of every heavy library, both
readings built their requests at once, images went out at 2500 px although the
model only looks at 768 px, and freed memory was never handed back to the OS."""

import base64
import io
import os
import subprocess
import sys

from PIL import Image

import grading
import grading_jobs
from conftest import fetch_one, make_assignment, make_student, make_submission


def test_importing_the_app_leaves_the_heavy_libraries_unloaded(tmp_path):
    env = {**os.environ, "DATA_DIR": str(tmp_path), "FLASK_SECRET_KEY": "x"}
    env.pop("RENDER", None)
    probe = "import app, sys; print([m for m in ('openai', 'sympy', 'pymupdf') if m in sys.modules])"
    result = subprocess.run([sys.executable, "-c", probe], env=env, capture_output=True, text=True,
                            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip().splitlines()[-1] == "[]"


def _sizes(parts):
    for part in parts:
        if part["type"] == "image_url":
            data = part["image_url"]["url"].split(",", 1)[1]
            yield Image.open(io.BytesIO(base64.b64decode(data))).size


def test_student_pages_go_out_at_the_resolution_gpt_4o_reads(tmp_path, monkeypatch):
    monkeypatch.setattr(grading, "TRANSCRIBE_MODEL", "gpt-4o")
    photo = tmp_path / "IMG_0001.jpg"
    Image.new("RGB", (3024, 4032), "white").save(photo)

    sizes = list(_sizes(grading._labelled_images("Student pages", [photo], with_strips=True)))

    assert len(sizes) == 1 + grading.STRIPS_PER_PAGE
    assert all(min(s) <= 768 and max(s) <= 2048 for s in sizes), sizes


def test_other_models_keep_the_full_resolution(tmp_path, monkeypatch):
    monkeypatch.setattr(grading, "TRANSCRIBE_MODEL", "gpt-5.5")
    photo = tmp_path / "IMG_0001.jpg"
    Image.new("RGB", (3024, 4032), "white").save(photo)

    [page_size, *_] = _sizes(grading._labelled_images("Student pages", [photo], with_strips=True))

    assert max(page_size) == 2500


def test_memory_is_handed_back_after_every_grading_job(monkeypatch):
    student_id = make_student()
    submission_id = make_submission(make_assignment(student_id), student_id)
    released = []
    monkeypatch.setattr(grading_jobs, "release_memory", lambda: released.append(True))

    monkeypatch.setattr(grading_jobs, "grade_submission", lambda *a, **k: {"problems": []})
    grading_jobs.start_grading_job(submission_id, [], "S")

    def fail(*a, **k):
        raise grading.GradingError("boom")
    monkeypatch.setattr(grading_jobs, "grade_submission", fail)
    grading_jobs.start_grading_job(submission_id, [], "S")

    assert released == [True, True]
    assert fetch_one("SELECT ai_status FROM student_submissions WHERE id = ?", (submission_id,))["ai_status"] == "error"
