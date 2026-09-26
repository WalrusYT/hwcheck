import sqlite3

import db


def test_migrations_add_columns_to_an_old_database_without_losing_rows():
    """Production already holds real data: init_db must upgrade it in place."""
    db.DB_PATH.unlink()
    conn = sqlite3.connect(db.DB_PATH)
    conn.executescript("""
        CREATE TABLE students (id INTEGER PRIMARY KEY, name TEXT NOT NULL, username TEXT NOT NULL UNIQUE,
            password_hash TEXT NOT NULL, language TEXT NOT NULL DEFAULT 'en', schedule_text TEXT,
            miro_link TEXT, zoom_link TEXT, performance_narrative TEXT, performance_narrative_updated_at TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')));
        INSERT INTO students (name, username, password_hash) VALUES ('Old', 'old', 'x');
    """)
    conn.commit()
    conn.close()

    db.init_db()
    db.init_db()  # idempotent

    conn = db.get_db()
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(students)")}
    row = conn.execute("SELECT name, curriculum FROM students").fetchone()
    conn.close()
    assert {"curriculum", "school_year", "tutor_notes", "first_login_at"} <= columns
    assert tuple(row) == ("Old", "other")
