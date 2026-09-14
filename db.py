"""SQLite storage for homework codes and student submissions."""

import os
import sqlite3
from pathlib import Path

DATA_DIR = Path(os.environ.get("DATA_DIR", Path(__file__).parent))
DB_PATH = DATA_DIR / "hwcheck.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS homeworks (
    code TEXT PRIMARY KEY,
    student_name TEXT NOT NULL,
    topic TEXT,
    task_files TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    homework_code TEXT NOT NULL,
    student_name TEXT NOT NULL,
    files TEXT NOT NULL DEFAULT '[]',
    ai_result TEXT,
    ai_status TEXT NOT NULL DEFAULT 'pending',
    ai_error TEXT,
    tutor_status TEXT NOT NULL DEFAULT 'new',
    tutor_notes TEXT,
    submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
    FOREIGN KEY (homework_code) REFERENCES homeworks(code)
);

CREATE TABLE IF NOT EXISTS students (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    language TEXT NOT NULL DEFAULT 'en',
    schedule_text TEXT,
    miro_link TEXT,
    zoom_link TEXT,
    performance_narrative TEXT,
    performance_narrative_updated_at TEXT,
    first_login_at TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS homework_assignments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    student_id INTEGER NOT NULL REFERENCES students(id),
    title TEXT NOT NULL,
    topic TEXT,
    task_files TEXT NOT NULL DEFAULT '[]',
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS student_submissions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES homework_assignments(id),
    student_id INTEGER NOT NULL REFERENCES students(id),
    files TEXT NOT NULL DEFAULT '[]',
    ai_result TEXT,
    ai_status TEXT NOT NULL DEFAULT 'pending',
    ai_error TEXT,
    tutor_grade TEXT,
    tutor_comment TEXT,
    tutor_result TEXT,
    feedback_published INTEGER NOT NULL DEFAULT 0,
    submitted_at TEXT NOT NULL DEFAULT (datetime('now')),
    reviewed_at TEXT
);

CREATE TABLE IF NOT EXISTS hint_chat_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    assignment_id INTEGER NOT NULL REFERENCES homework_assignments(id),
    student_id INTEGER NOT NULL REFERENCES students(id),
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient_type TEXT NOT NULL,
    recipient_id INTEGER,
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT,
    link TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db():
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = get_db()
    conn.executescript(SCHEMA)
    # Migration for databases created before task_files existed.
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(homeworks)")}
    if "task_files" not in columns:
        conn.execute("ALTER TABLE homeworks ADD COLUMN task_files TEXT NOT NULL DEFAULT '[]'")
    # Migration for databases created before first_login_at existed.
    student_columns = {row["name"] for row in conn.execute("PRAGMA table_info(students)")}
    if "first_login_at" not in student_columns:
        conn.execute("ALTER TABLE students ADD COLUMN first_login_at TEXT")
    # Migration for databases created before tutor_result existed.
    submission_columns = {row["name"] for row in conn.execute("PRAGMA table_info(student_submissions)")}
    if "tutor_result" not in submission_columns:
        conn.execute("ALTER TABLE student_submissions ADD COLUMN tutor_result TEXT")
    conn.commit()
    conn.close()
