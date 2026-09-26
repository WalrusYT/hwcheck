"""Shared paths and constants."""

import os
from pathlib import Path

# Render sets RENDER=true on every service; nothing else distinguishes production.
IS_PRODUCTION = os.environ.get("RENDER") == "true"

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
UPLOAD_DIR = DATA_DIR / "uploads"
ASSIGNMENT_FILES_DIR = UPLOAD_DIR / "assignments"
SUBMISSION_FILES_DIR = UPLOAD_DIR / "student_submissions"
# Answer keys live outside ASSIGNMENT_FILES_DIR as defense in depth: no
# student-facing route serves anything from this tree.
SOLUTION_FILES_DIR = UPLOAD_DIR / "solutions"

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".heic", ".heif", ".pdf"}
MAX_FILES = 10

CURRICULA = ("pt", "ru", "other")
