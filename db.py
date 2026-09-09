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
    conn.commit()
    conn.close()
