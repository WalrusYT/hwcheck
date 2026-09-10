"""In-app notifications for the tutor (admin, single shared account) and students."""

import db


def notify_admin(type_, title, body=None, link=None):
    conn = db.get_db()
    conn.execute(
        "INSERT INTO notifications (recipient_type, recipient_id, type, title, body, link) "
        "VALUES ('admin', NULL, ?, ?, ?, ?)",
        (type_, title, body, link),
    )
    conn.commit()
    conn.close()


def notify_student(student_id, type_, title, body=None, link=None):
    conn = db.get_db()
    conn.execute(
        "INSERT INTO notifications (recipient_type, recipient_id, type, title, body, link) "
        "VALUES ('student', ?, ?, ?, ?, ?)",
        (student_id, type_, title, body, link),
    )
    conn.commit()
    conn.close()


def get_admin_notifications(limit=8):
    conn = db.get_db()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE recipient_type = 'admin' ORDER BY created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    conn.close()
    return rows


def count_unread_admin():
    conn = db.get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE recipient_type = 'admin' AND is_read = 0"
    ).fetchone()
    conn.close()
    return row["c"]


def get_student_notifications(student_id, limit=8):
    conn = db.get_db()
    rows = conn.execute(
        "SELECT * FROM notifications WHERE recipient_type = 'student' AND recipient_id = ? "
        "ORDER BY created_at DESC LIMIT ?",
        (student_id, limit),
    ).fetchall()
    conn.close()
    return rows


def count_unread_student(student_id):
    conn = db.get_db()
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE recipient_type = 'student' "
        "AND recipient_id = ? AND is_read = 0",
        (student_id,),
    ).fetchone()
    conn.close()
    return row["c"]


def mark_all_read_admin():
    conn = db.get_db()
    conn.execute("UPDATE notifications SET is_read = 1 WHERE recipient_type = 'admin'")
    conn.commit()
    conn.close()


def mark_all_read_student(student_id):
    conn = db.get_db()
    conn.execute(
        "UPDATE notifications SET is_read = 1 WHERE recipient_type = 'student' AND recipient_id = ?",
        (student_id,),
    )
    conn.commit()
    conn.close()
