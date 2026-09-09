"""AI homework grading: reads submitted photos/PDFs, solves each problem
independently, and grades the student's work against that solution.

This is a first pass for the tutor to review, not a final grade - low
confidence and unclear items are flagged rather than guessed at.
"""

import base64
import json
import os

import pymupdf as fitz
from openai import OpenAI

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

SYSTEM_PROMPT = """\
You are an experienced math tutor reviewing a student's homework submission \
for another tutor, who will double-check your work before it reaches the \
student. You will be shown images labeled as one or both of:
- "Assigned homework" - the original problem sheet the tutor gave the \
student. Treat this as the authoritative list of problems, if present.
- "Student submission" - the student's photographed/scanned answers. This \
may or may not also include the printed problem text alongside their work.

Match each problem in the student submission to the corresponding problem \
on the assigned homework sheet when both are provided (by number/label, or \
by content if labels differ). If only a student submission is given, work \
from whatever problem text appears there.

For every problem you can actually see:
- Restate the problem briefly.
- Solve it yourself, independently, step by step.
- Compare your solution to the student's answer and shown work.
- Give a verdict: "correct", "incorrect", "partially_correct" (right idea/
  method but a slip, or correct answer with missing steps), or "unclear"
  (you cannot confidently read the problem or the student's work).
- Explain briefly why, in a way the tutor can quickly verify and forward to
  the student - mention the specific step where the student went wrong, if
  any.
- Rate your own confidence as "high", "medium", or "low". Use "low" whenever
  handwriting, notation, or a cropped/blurry image makes you unsure.

Do not invent problems that are not visible in the images. If the images
contain no readable math problems at all, return an empty problems list and
explain why in overall_summary. Never let the student see this directly -
you are producing a draft for the tutor's review only, so be candid about
uncertainty rather than smoothing it over.

Work through every problem and decide its verdict first. Only after that,
write overall_summary and estimated_score by tallying up the verdicts you
just gave - they must agree with the per-problem verdicts, never contradict
them.
"""

RESULT_SCHEMA = {
    "name": "homework_grading_result",
    "schema": {
        "type": "object",
        "properties": {
            "problems": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "problem_label": {"type": "string", "description": "e.g. 'Q1' or '3b'"},
                        "problem_text": {"type": "string"},
                        "student_answer": {"type": "string"},
                        "correct_answer": {"type": "string"},
                        "verdict": {
                            "type": "string",
                            "enum": ["correct", "incorrect", "partially_correct", "unclear"],
                        },
                        "explanation": {"type": "string"},
                        "confidence": {"type": "string", "enum": ["high", "medium", "low"]},
                    },
                    "required": [
                        "problem_label",
                        "problem_text",
                        "student_answer",
                        "correct_answer",
                        "verdict",
                        "explanation",
                        "confidence",
                    ],
                    "additionalProperties": False,
                },
            },
            "flags_for_tutor": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Anything the tutor should double check by hand before sending this to the student.",
            },
            "estimated_score": {
                "type": "string",
                "description": "Score derived by counting the verdicts above, e.g. '7/10 problems correct'. Must be consistent with the verdicts in 'problems'.",
            },
            "overall_summary": {
                "type": "string",
                "description": "2-3 sentence summary of how the student did overall, for the tutor. Must be consistent with the verdicts in 'problems' - do not describe a problem as correct here if you marked it incorrect above.",
            },
        },
        "required": ["problems", "flags_for_tutor", "estimated_score", "overall_summary"],
        "additionalProperties": False,
    },
    "strict": True,
}


class GradingError(Exception):
    pass


def _file_to_image_data_urls(file_path):
    """Convert an uploaded image or PDF into a list of base64 data URLs (one per page/image)."""
    ext = file_path.suffix.lower()
    urls = []
    if ext == ".pdf":
        doc = fitz.open(file_path)
        try:
            for page in doc:
                pix = page.get_pixmap(dpi=200)
                png_bytes = pix.tobytes("png")
                b64 = base64.b64encode(png_bytes).decode("utf-8")
                urls.append(f"data:image/png;base64,{b64}")
        finally:
            doc.close()
    else:
        media_type = "image/jpeg" if ext in (".jpg", ".jpeg") else "image/png"
        with open(file_path, "rb") as f:
            b64 = base64.b64encode(f.read()).decode("utf-8")
        urls.append(f"data:{media_type};base64,{b64}")
    return urls


def grade_submission(file_paths, student_name, topic=None, task_file_paths=None):
    """file_paths: list of pathlib.Path to the student's uploaded files.
    task_file_paths: optional list of pathlib.Path to the tutor's uploaded
    homework/problem sheet, if one was attached when the code was created.
    Returns a dict matching RESULT_SCHEMA.
    """
    client = OpenAI()

    content = [{
        "type": "text",
        "text": (
            f"Student: {student_name}\n"
            f"Homework topic/context (may be blank): {topic or '(none provided)'}\n"
        ),
    }]

    if task_file_paths:
        content.append({"type": "text", "text": "Assigned homework (the problem sheet the tutor gave the student):"})
        for file_path in task_file_paths:
            for url in _file_to_image_data_urls(file_path):
                content.append({"type": "image_url", "image_url": {"url": url}})

    content.append({"type": "text", "text": "Student submission (grade this):"})
    for file_path in file_paths:
        for url in _file_to_image_data_urls(file_path):
            content.append({"type": "image_url", "image_url": {"url": url}})

    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_schema", "json_schema": RESULT_SCHEMA},
        )
    except Exception as exc:
        raise GradingError(str(exc)) from exc

    try:
        return json.loads(response.choices[0].message.content)
    except (json.JSONDecodeError, IndexError, AttributeError) as exc:
        raise GradingError(f"Could not parse AI response: {exc}") from exc
