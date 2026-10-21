"""Grade averaging and AI-generated performance narrative for a student."""

import logging
import threading

import db
import llm

log = logging.getLogger(__name__)

GRADE_POINTS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
POINTS_TO_LETTER = [(3.5, "A"), (2.5, "B"), (1.5, "C"), (0.5, "D"), (-1, "F")]

# There are no due dates: homework with no photos a week after it was set counts as
# not handed in. Until then it is neither handed in nor missed.
MISSED_AFTER_DAYS = 7

NARRATIVE_PROMPT = {
    "en": (
        "You are a supportive math tutor's assistant writing a short performance "
        "summary about a student, for the student themselves to read. Given their "
        "recent homework grades, the tutor's comments and how much of the set "
        "homework they handed in, write 3-4 sentences in English: how they're "
        "doing overall, one specific thing going well, and one specific, concrete "
        "thing to improve. If some homework was not handed in, say so plainly in "
        "one sentence as something to change - doing it regularly matters as much "
        "as the grades; if everything was handed in, don't mention it. With no "
        "graded homework there is nothing to praise yet: don't name a strength - "
        "say the homework hasn't been handed in and suggest one concrete first "
        "step. Write homework titles exactly as given, untranslated. Be "
        "encouraging but honest - do not exaggerate if performance is "
        "weak, and do not invent details not supported by the data given."
    ),
    "ru": (
        "Ты - доброжелательный ассистент репетитора по математике, который "
        "составляет короткую сводку об успеваемости ученика, которую прочитает "
        "сам ученик. На основе недавних оценок за домашние задания, комментариев "
        "репетитора и того, сколько выданных домашних заданий ученик сдал, напиши "
        "3-4 предложения на русском языке: как в целом обстоят дела, что-то одно "
        "конкретное, что получается хорошо, и что-то одно конкретное, над чем "
        "стоит поработать. Если какие-то домашние задания не сданы, прямо скажи об "
        "этом одним предложением как о том, что нужно изменить: делать их "
        "регулярно так же важно, как оценки; если всё сдано, не упоминай этого. "
        "Если оценённых работ нет, хвалить пока не за что: не называй сильных "
        "сторон - скажи, что домашние задания не сданы, и предложи один "
        "конкретный первый шаг. Названия домашних заданий пиши точно как в "
        "данных - португальские оставляй латиницей (например, «Potências»), не "
        "переводи их. Будь доброжелательным, но честным - не "
        "преувеличивай, если успеваемость слабая, и не придумывай детали, не "
        "подтверждённые данными."
    ),
}


def homework_record(conn, student_id):
    """What the performance views show about a student's homework: graded (published,
    newest first), missed (no photos MISSED_AFTER_DAYS after it was set, newest first),
    handed_in / due counts and the average of the grades. Homework still within its
    week counts for neither; homework waiting for the tutor is handed in."""
    graded = conn.execute(
        """SELECT ss.*, ha.title AS assignment_title
           FROM student_submissions ss
           JOIN homework_assignments ha ON ha.id = ss.assignment_id
           WHERE ss.student_id = ? AND ss.feedback_published = 1
           ORDER BY ss.reviewed_at DESC""",
        (student_id,),
    ).fetchall()
    missed = conn.execute(
        """SELECT ha.id, ha.title, ha.created_at
           FROM homework_assignments ha
           WHERE ha.student_id = ? AND ha.created_at <= datetime('now', ?)
             AND NOT EXISTS (SELECT 1 FROM student_submissions ss
                             WHERE ss.assignment_id = ha.id AND ss.student_id = ha.student_id)
           ORDER BY ha.created_at DESC""",
        (student_id, f"-{MISSED_AFTER_DAYS} days"),
    ).fetchall()
    handed_in = conn.execute(
        "SELECT COUNT(DISTINCT assignment_id) FROM student_submissions WHERE student_id = ?", (student_id,)
    ).fetchone()[0]
    letter, gpa = compute_average([g["tutor_grade"] for g in graded])
    return {"graded": graded, "missed": missed, "handed_in": handed_in, "due": handed_in + len(missed),
            "letter": letter, "gpa": gpa}


def compute_average(grades):
    """grades: list of letter grade strings ('A'..'F'). Returns (letter, gpa_float) or (None, None)."""
    points = [GRADE_POINTS[g] for g in grades if g in GRADE_POINTS]
    if not points:
        return None, None
    avg = sum(points) / len(points)
    for threshold, letter in POINTS_TO_LETTER:
        if avg >= threshold:
            return letter, round(avg, 2)
    return "F", round(avg, 2)


def generate_narrative(student_name, history, lang="en", missed=(), handed_in=None, due=None):
    """history: list of {"title": str, "grade": str, "comment": str|None} for graded submissions,
    most recent first; missed: titles of homework not handed in. Returns a short narrative
    string, or None if there's nothing to summarize.
    """
    if not history and not missed:
        return None

    lines = [f"Student: {student_name}"]
    if due:
        lines.append(f"Handed in: {handed_in} of {due} homework assignments set")
    if missed:
        lines.append("Not handed in: " + "; ".join(missed))
    for item in history:
        line = f"- {item['title']}: grade {item['grade']}"
        if item.get("comment"):
            line += f" - tutor comment: {item['comment']}"
        lines.append(line)
    user_content = "\n".join(lines)

    system_prompt = NARRATIVE_PROMPT.get(lang, NARRATIVE_PROMPT["en"])
    return llm.complete(
        [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_content}],
        max_tokens=2000,
    )


def refresh_narrative(student_id):
    """Regenerate and cache the student's performance narrative in their current language.
    On failure the previous narrative is kept - the grades themselves never depend on it."""
    conn = db.get_db()
    try:
        student = conn.execute("SELECT * FROM students WHERE id = ?", (student_id,)).fetchone()
        if student is None:
            return
        record = homework_record(conn, student_id)
        history = [{"title": r["assignment_title"], "grade": r["tutor_grade"], "comment": r["tutor_comment"]}
                   for r in record["graded"][:15]]
        try:
            narrative = generate_narrative(student["name"], history, lang=student["language"],
                                           missed=[m["title"] for m in record["missed"][:10]],
                                           handed_in=record["handed_in"], due=record["due"])
        except llm.LLMError:
            log.exception("performance narrative for student %s failed; keeping the previous one", student_id)
            return
        conn.execute(
            "UPDATE students SET performance_narrative = ?, performance_narrative_updated_at = datetime('now') "
            "WHERE id = ?",
            (narrative, student_id),
        )
        conn.commit()
    finally:
        conn.close()


def _run_in_background(fn, *args):
    threading.Thread(target=fn, args=args, daemon=True).start()


def refresh_narrative_in_background(student_id):
    """Publishing feedback and switching language shouldn't wait several seconds on an AI call."""
    _run_in_background(refresh_narrative, student_id)
