"""Shared path/constant config used by both blueprints."""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
UPLOAD_DIR = DATA_DIR / "uploads"
ASSIGNMENT_FILES_DIR = UPLOAD_DIR / "assignments"
SUBMISSION_FILES_DIR = UPLOAD_DIR / "student_submissions"
# Kept out of ASSIGNMENT_FILES_DIR on purpose: the student-facing task-file
# route only checks that the assignment belongs to the student, not that the
# requested filename is actually in task_files, so anything living under
# ASSIGNMENT_FILES_DIR is reachable by a student who guesses its name. An
# answer key must never be reachable that way.
SOLUTION_FILES_DIR = UPLOAD_DIR / "solutions"

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".pdf"}
MAX_FILES = 10
