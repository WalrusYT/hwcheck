"""Shared path/constant config used by both blueprints."""

import os
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
UPLOAD_DIR = DATA_DIR / "uploads"
ASSIGNMENT_FILES_DIR = UPLOAD_DIR / "assignments"
SUBMISSION_FILES_DIR = UPLOAD_DIR / "student_submissions"

ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".webp", ".pdf"}
MAX_FILES = 10
