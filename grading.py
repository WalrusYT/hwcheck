"""AI homework grading: reads submitted photos/PDFs, solves each problem
independently, and grades the student's work against that solution.

This is a first pass for the tutor to review, not a final grade - low
confidence and unclear items are flagged rather than guessed at.
"""

import json
import os

from openai import OpenAI

from image_utils import file_to_image_data_urls

MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o")

SYSTEM_PROMPT = """\
You are an experienced math tutor reviewing a student's homework submission \
for another tutor, who will double-check your work before it reaches the \
student. You will be shown images labeled as one or more of:
- "Assigned homework" - the original problem sheet the tutor gave the \
student. Treat this as the authoritative list of problems, if present.
- "Tutor's solutions" - the tutor's own worked answers/answer key for this \
assignment (not the student's work). When present, use these as the \
ground truth for each correct_answer instead of solving the problem \
yourself from scratch - but still sanity-check each one, and note in \
flags_for_tutor if a provided solution looks wrong or doesn't match the \
problem statement. Still independently judge the student's own shown work \
for verdict and explanation - a correct final answer with a broken method \
is still "partially_correct", regardless of what the answer key says.
- "Student submission" - the student's photographed/scanned answers. This \
may or may not also include the printed problem text alongside their work.

Multiple images may be provided across both groups - each image is preceded
by a label saying "page X of Y" for that group, so you know exactly how
many pages to expect. You MUST examine every single page in both groups
before writing your answer - do not stop early or skip any page, even if
the images are numerous or partially redundant with each other.

Match each problem in the student submission to the corresponding problem
on the assigned homework sheet when both are provided (by number/label, or
by content if labels differ) - a problem shown on the assigned sheet AND
again (e.g. copied out by the student before their handwritten work) in the
submission is the SAME problem, not two. Before writing your final answer,
first mentally list every distinct problem number/label you can find across
ALL pages of both groups combined, then make sure your "problems" array
contains exactly that list - each problem_label appearing EXACTLY ONCE,
with all information about it merged into that single entry. Never output
the same problem_label twice. If only a student submission is given, work
from whatever problem text appears there.

When a problem has multiple lettered or numbered sub-parts (e.g. a question
"1.2" printed with sub-items a) b) c) d)... on the assigned sheet), treat
EACH sub-part as its own separate entry in "problems" (labeled e.g. "1.2a",
"1.2b", ...) - do not collapse them into one entry, and do not silently stop
at whichever sub-part the student happened to answer last. If the assigned
sheet shows 8 sub-parts and the student's work only covers the first two,
your output must still contain all 8 entries - the missing six are real
information for the tutor (see "not_attempted" below), not something to
quietly omit because they'd make the list longer.

NEVER FABRICATE A STUDENT ANSWER. If you cannot find a student's answer to
a problem or sub-part anywhere in the submission images - it was skipped,
cut off, or the page is missing - set student_answer to an empty string and
verdict to "not_attempted". Do this even when the assigned sheet or your own
solution makes it obvious what the "expected" answer would be - it is never
acceptable to write down the correct answer (or anything else you did not
actually read off the student's own work) as if the student wrote it, and
it is never acceptable to mark a problem "correct" because you assume the
student would have gotten it right. student_answer must always be a
faithful transcription of what is actually visible in the student's
handwriting - if it is genuinely ambiguous, transcribe your best reading
and use "unclear" with low confidence, rather than silently resolving the
ambiguity toward whatever answer happens to be correct.

Empty sets: when an interval or set operation (e.g. an intersection with no
overlap) has no solution, the answer is the empty set - write it as
\\(\\emptyset\\) (or "empty set"), never as a reversed-order interval like
[5,3] or [3,2] where the left bound is larger than the right - that
notation is non-standard and confusing, and silently writing it instead of
recognizing "this means empty set" is a mistake. This applies to both your
own correct_answer and to reading the student's handwriting: if the student
wrote the empty-set symbol (\\(\\emptyset\\)), empty braces {}, "vazio", or
similar, transcribe their student_answer faithfully as \\(\\emptyset\\) -
do not substitute a numeric interval that merely resembles your own
computed bounds instead of what they actually wrote.

For every problem you can actually see:
- Transcribe the problem's numbers, symbols, bounds, and notation precisely
  before solving - re-read them carefully. A single misread digit or symbol
  (e.g. confusing similar-looking numerals, an interval bound, a sign, or a
  bracket type) will silently produce a wrong "correct_answer" even though
  your arithmetic afterward is flawless. If any specific character is
  genuinely hard to make out, say so explicitly in explanation and in
  flags_for_tutor, and lower confidence - do not silently guess and report
  high confidence.
- Restate the problem briefly (after the careful transcription above).
- Solve it yourself, independently, step by step.
- Compare your solution to the student's answer and shown work.
- Give a verdict: "correct", "incorrect", "partially_correct" (right idea/
  method but a slip, or correct answer with missing steps), "unclear" (the
  student attempted it but the handwriting or notation is too ambiguous to
  confidently read), or "not_attempted" (no student work for this problem
  exists anywhere in the images at all - see above, and never use this as a
  substitute for actually looking).
- If the verdict is "correct", leave explanation as an empty string - no
  need to explain a correct answer. For "not_attempted", leave explanation
  as an empty string too. For any other verdict ("incorrect",
  "partially_correct", "unclear"), explain briefly why, in a way the tutor
  can quickly verify and forward to the student - mention the specific step
  where the student went wrong, if any.
- Rate your own confidence as "high", "medium", or "low". Use "low" whenever
  handwriting, notation, or a cropped/blurry image makes you unsure. Use
  "high" for "not_attempted" only when you are certain the problem is
  genuinely absent, not just hard to find.

Do not invent problems that are not visible in the images. If the images
contain no readable math problems at all, return an empty problems list and
explain why in overall_summary. Never let the student see this directly -
you are producing a draft for the tutor's review only, so be candid about
uncertainty rather than smoothing it over.

Work through every problem and decide its verdict first. Only after that,
write overall_summary and estimated_score by tallying up the verdicts you
just gave - they must agree with the per-problem verdicts, never contradict
them.

Formatting: whenever you write mathematical notation anywhere in your output
(problem_text, student_answer, correct_answer, explanation, overall_summary)
- fractions, exponents, roots, plus-minus, etc. - wrap it in inline LaTeX
delimiters like \\(x = \\frac{1}{2}\\), so it can be rendered. Plain
expressions with no special notation (e.g. "x = 5") don't need delimiters.
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
                            "enum": ["correct", "incorrect", "partially_correct", "unclear", "not_attempted"],
                        },
                        "explanation": {
                            "type": "string",
                            "description": "Empty string if verdict is 'correct' or 'not_attempted'. Otherwise a brief explanation of the mistake.",
                        },
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


def grade_submission(file_paths, student_name, topic=None, task_file_paths=None,
                      solution_file_paths=None, tutor_note=None):
    """file_paths: list of pathlib.Path to the student's uploaded files.
    task_file_paths: optional list of pathlib.Path to the tutor's uploaded
    homework/problem sheet, if one was attached when the code was created.
    solution_file_paths: optional list of pathlib.Path to the tutor's own
    worked solutions/answer key for this assignment, if one was attached -
    used as ground truth so the AI doesn't have to solve from scratch.
    tutor_note: optional string - a tutor's correction on a previous grading
    attempt of this same submission (e.g. "you misread interval A's upper
    bound as 0, it's actually 3"), used to prompt a careful re-check.
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

    if tutor_note:
        content.append({
            "type": "text",
            "text": (
                "IMPORTANT - this is a re-check. A tutor already reviewed a previous "
                "AI grading attempt on this exact submission and left one or more "
                "corrections below, each pointing at a specific problem by its label:\n"
                f"{tutor_note}\n"
                "Re-read the images from scratch, paying close attention to the "
                "specific problems and issues described above, and re-check every "
                "problem (not just the ones mentioned) in case the same kind of "
                "misreading affected other answers too."
            ),
        })

    def append_labeled_pages(group_label, paths):
        urls = []
        for file_path in paths:
            urls.extend(file_to_image_data_urls(file_path))
        if not urls:
            return
        content.append({"type": "text", "text": f"{group_label} - {len(urls)} page(s) total:"})
        for i, url in enumerate(urls, 1):
            content.append({"type": "text", "text": f"{group_label}, page {i} of {len(urls)}:"})
            content.append({"type": "image_url", "image_url": {"url": url}})

    if task_file_paths:
        append_labeled_pages("Assigned homework (the problem sheet the tutor gave the student)", task_file_paths)

    if solution_file_paths:
        append_labeled_pages(
            "Tutor's solutions (ground truth answer key - not the student's work)", solution_file_paths
        )

    append_labeled_pages("Student submission (grade this)", file_paths)

    try:
        response = client.chat.completions.create(
            model=MODEL,
            max_tokens=8000,
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
