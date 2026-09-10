"""Grade averaging and AI-generated performance narrative for a student."""

import os

from openai import OpenAI

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

GRADE_POINTS = {"A": 4, "B": 3, "C": 2, "D": 1, "F": 0}
POINTS_TO_LETTER = [(3.5, "A"), (2.5, "B"), (1.5, "C"), (0.5, "D"), (-1, "F")]

NARRATIVE_PROMPT = {
    "en": (
        "You are a supportive math tutor's assistant writing a short performance "
        "summary about a student, for the student themselves to read. Given their "
        "recent homework grades and the tutor's comments, write 3-4 sentences in "
        "English: how they're doing overall, one specific thing going well, and "
        "one specific, concrete thing to improve. Be encouraging but honest - do "
        "not exaggerate if performance is weak, and do not invent details not "
        "supported by the data given."
    ),
    "ru": (
        "Ты - доброжелательный ассистент репетитора по математике, который "
        "составляет короткую сводку об успеваемости ученика, которую прочитает "
        "сам ученик. На основе недавних оценок за домашние задания и комментариев "
        "репетитора напиши 3-4 предложения на русском языке: как в целом обстоят "
        "дела, что-то одно конкретное, что получается хорошо, и что-то одно "
        "конкретное, над чем стоит поработать. Будь доброжелательным, но честным - "
        "не преувеличивай, если успеваемость слабая, и не придумывай детали, не "
        "подтверждённые данными."
    ),
}


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


def generate_narrative(student_name, history, lang="en"):
    """history: list of {"title": str, "grade": str, "comment": str|None} for graded submissions,
    most recent first. Returns a short narrative string, or None if there's nothing to summarize.
    """
    if not history:
        return None

    lines = [f"Student: {student_name}"]
    for item in history:
        line = f"- {item['title']}: grade {item['grade']}"
        if item.get("comment"):
            line += f" - tutor comment: {item['comment']}"
        lines.append(line)
    user_content = "\n".join(lines)

    client = OpenAI()
    system_prompt = NARRATIVE_PROMPT.get(lang, NARRATIVE_PROMPT["en"])
    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
    )
    return response.choices[0].message.content
