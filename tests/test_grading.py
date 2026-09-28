import json

import pytest
from PIL import Image

import grading
import grading_jobs
import llm
from conftest import fetch_one, make_assignment, make_student, make_submission


def transcription(*problems, notes=()):
    return {"problems": [
        {"label": label, "problem_text": text, "found": found, "student_work": "",
         "student_final_answer": answer, "legibility": legibility}
        for label, text, answer, found, legibility in problems
    ], "notes": list(notes)}


def graded(*problems, summary="ok"):
    return {"problems": [
        {"label": label, "work": "work", "problem_expr": pexpr, "correct_expr": cexpr, "student_expr": sexpr,
         "answer_kind": kind, "correct_answer": correct, "verdict": verdict, "explanation": "why",
         "confidence": "high"}
        for label, kind, pexpr, cexpr, sexpr, correct, verdict in problems
    ], "flags_for_tutor": [], "estimated_score": "ignored", "overall_summary": summary}


@pytest.fixture
def page(tmp_path):
    path = tmp_path / "page.jpg"
    Image.new("RGB", (400, 600), "white").save(path)
    return [path]


def test_answer_key_that_is_wrong_gets_replaced(fake_llm, page):
    reading = transcription(("63a", "x/(y-1)+5/(1-y)", "\\frac{x-5}{y-1}", True, "clear"))
    fake_llm.reply("homework_transcription", reading)
    fake_llm.reply("homework_grading", graded(
        ("63a", "expression", "x/(y-1)+5/(1-y)", "0", "(x-5)/(y-1)", "\\(0\\)", "incorrect")))

    result = grading.grade_submission(page, "Student", "fractions", task_file_paths=page)

    problem = result["problems"][0]
    assert problem["correct_answer"] == "\\(\\frac{x - 5}{y - 1}\\)"
    assert problem["verdict"] == "partially_correct"  # value is right; tutor decides on simplification
    assert any("answer key was wrong" in flag for flag in result["flags_for_tutor"])


def test_exact_check_overrules_a_false_correct(fake_llm, page):
    fake_llm.reply("homework_transcription", transcription(("1", "2x+1=7", "x=4", True, "clear")))
    fake_llm.reply("homework_grading", graded(("1", "equation", "2*x+1=7", "3", "4", "3", "correct")))

    problem = grading.grade_submission(page, "S", None, task_file_paths=page)["problems"][0]

    assert problem["verdict"] == "incorrect"


def test_without_a_sheet_wrong_verdicts_become_unclear_but_correct_ones_stand(fake_llm, page):
    fake_llm.reply("homework_transcription", transcription(
        ("1", "2x+1=7", "x=3", True, "clear"), ("2", "x+1=2", "x=5", True, "clear")))
    fake_llm.reply("homework_grading", graded(
        ("1", "equation", "2*x+1=7", "3", "3", "3", "correct"),
        ("2", "equation", "x+1=2", "1", "5", "1", "incorrect")))

    result = grading.grade_submission(page, "S", None)

    assert [p["verdict"] for p in result["problems"]] == ["correct", "unclear"]
    assert any("No homework sheet attached" in flag for flag in result["flags_for_tutor"])


def test_disagreeing_readings_are_marked_unclear_not_graded(fake_llm, page):
    fake_llm.reply("homework_transcription",
                   transcription(("10.2", "", "180-146=34", True, "clear")),
                   transcription(("10.2", "", "180-136=44", True, "clear")))
    fake_llm.reply("homework_grading", graded(("10.2", "number", "", "34", "34", "34", "correct")))

    result = grading.grade_submission(page, "S", None)

    assert result["problems"][0]["verdict"] == "unclear"
    assert result["problems"][0]["explanation"] == ""
    assert any("two readings disagree" in flag for flag in result["flags_for_tutor"])


def test_unanswered_problem_is_not_attempted_even_if_the_grader_says_correct(fake_llm, page):
    fake_llm.reply("homework_transcription", transcription(("8", "Choose the true statement", "", False, "clear")))
    fake_llm.reply("homework_grading", graded(("8", "choice", "", "D", "D", "D", "correct")))

    problem = grading.grade_submission(page, "S", None)["problems"][0]

    assert (problem["verdict"], problem["student_answer"]) == ("not_attempted", "")


def test_tutor_corrected_answer_replaces_the_ai_reading(fake_llm, page):
    fake_llm.reply("homework_transcription",
                   transcription(("1", "2x+1=7", "x=4", True, "clear")),
                   transcription(("1", "2x+1=7", "x=1", True, "clear")))
    fake_llm.reply("homework_grading", graded(("1", "equation", "2*x+1=7", "3", "3", "3", "correct")))

    result = grading.grade_submission(page, "S", None, known_answers={"1": "x=3"})

    assert result["problems"][0]["student_answer"] == "x=3"
    assert result["problems"][0]["verdict"] == "correct"  # not marked unclear: the tutor settled the reading
    sent = json.dumps(fake_llm.calls[-1]["messages"], ensure_ascii=False)
    assert "x=3" in sent and "x=4" not in sent


def test_reading_pass_never_sees_the_answer_key(fake_llm, page, tmp_path):
    key = tmp_path / "key.jpg"
    Image.new("RGB", (200, 200), "white").save(key)
    fake_llm.reply("homework_transcription", transcription(("1", "", "5", True, "clear")))
    fake_llm.reply("homework_grading", graded(("1", "number", "", "5", "5", "5", "correct")))

    grading.grade_submission(page, "S", None, solution_file_paths=[key])

    reading_calls = [c for c in fake_llm.calls if c["kind"] == "homework_transcription"]
    assert all("answer key" not in json.dumps(c["messages"]).lower() for c in reading_calls)
    grading_call = next(c for c in fake_llm.calls if c["kind"] == "homework_grading")
    assert "answer key" in json.dumps(grading_call["messages"]).lower()


def test_grader_sees_the_printed_sheet_not_only_the_readers_copy_of_it(fake_llm, page, tmp_path):
    """The reader copied a multiple-choice question without its options a)-d), so the
    grader saw the answer "c" with no idea what c was and marked a right answer wrong."""
    sheet = tmp_path / "sheet.jpg"
    Image.new("RGB", (300, 400), "white").save(sheet)
    fake_llm.reply("homework_transcription", transcription(("9", "Qual dos seguintes números está entre 0,4 e 0,3?",
                                                            "c", True, "clear")))
    fake_llm.reply("homework_grading", graded(("9", "choice", "", "c", "c", "c", "correct")))

    grading.grade_submission(page, "S", None, task_file_paths=[sheet])

    grading_call = next(c for c in fake_llm.calls if c["kind"] == "homework_grading")
    content = grading_call["messages"][1]["content"]
    assert any(part.get("type") == "image_url" for part in content)
    assert "assigned homework sheet" in json.dumps(content).lower()


def test_empty_set_spellings_and_crossed_out_marks_are_one_reading(fake_llm, page):
    """\\emptyset vs \\varnothing (and a crossed-out ∅ next to the real answer) made five
    of a student's answers "unclear" although both readings said the same thing."""
    fake_llm.reply("homework_transcription",
                   transcription(("8a", "", "\\(max=1\\)", True, "clear"),
                                 ("8c", "", "\\(max=\\emptyset\\)", True, "clear")),
                   transcription(("(8)a)", "", "\\(max=\\cancel{\\varnothing}\\;1\\)", True, "clear"),
                                 ("(8)c)", "", "\\(max=\\varnothing\\)", True, "clear")))
    fake_llm.reply("homework_grading", graded(("8a", "text", "", "", "", "1", "correct"),
                                              ("8c", "text", "", "", "", "none", "correct")))

    result = grading.grade_submission(page, "S", None, task_file_paths=page)

    assert [p["verdict"] for p in result["problems"]] == ["correct", "correct"]
    assert not any("disagree" in flag for flag in result["flags_for_tutor"])


def test_disagreement_flag_shows_the_latex_as_written():
    """repr() doubled every backslash, so the tutor saw '\\\\(x=4\\\\)' instead of math."""
    paired = grading.reconcile(transcription(("1", "", "\\(x=4\\)", True, "clear")),
                               transcription(("1", "", "\\(x=1\\)", True, "clear")))
    note = paired[0][1]
    assert "\\(x=4\\)" in note and "\\(x=1\\)" in note and "\\\\" not in note


def test_unanswered_problems_are_not_sent_to_the_grader(fake_llm, page):
    """The grader used to receive blank problems and invent "no problem statement was
    available" for them, and the summary blamed that for them being unanswered."""
    fake_llm.reply("homework_transcription", transcription(("8a", "", "1", True, "clear"),
                                                           ("12", "", "", False, "clear")))
    fake_llm.reply("homework_grading", graded(("8a", "number", "", "1", "1", "1", "correct")))

    result = grading.grade_submission(page, "S", None, task_file_paths=page)

    grading_call = next(c for c in fake_llm.calls if c["kind"] == "homework_grading")
    assert '"12"' not in json.dumps(grading_call["messages"])
    assert [p["verdict"] for p in result["problems"]] == ["correct", "not_attempted"]
    assert result["estimated_score"] == "1 of 1 answered problems correct; 1 not attempted"


def test_nothing_to_grade_skips_the_grader(fake_llm, page):
    fake_llm.reply("homework_transcription", transcription(("12", "", "", False, "clear")))

    result = grading.grade_submission(page, "S", None, task_file_paths=page)

    assert not any(c["kind"] == "homework_grading" for c in fake_llm.calls)
    assert result["problems"][0]["verdict"] == "not_attempted"


def test_multi_part_readings_are_compared_part_by_part():
    """One reading listed inf/sup/min/max, the other also the interior and limit points
    and wrote \\inf for inf - the same answer, but every such problem became "unclear"."""
    short = transcription(("9b", "", "inf = 5 ; sup = 15 ; min = \\varnothing ; max = 15", True, "clear"))
    full = transcription(("9b", "", "Int = [5,7]; \\text{limit points} = \\{15\\}; \\inf = 5; \\sup = 15; "
                                    "\\min = \\emptyset; \\max = 15", True, "clear"))
    [(problem, note)] = grading.reconcile(short, full)
    assert note is None
    assert "limit points" in problem["student_final_answer"]  # the fuller reading is the one graded


def test_part_names_match_across_latex_wrapping():
    [(_, note)] = grading.reconcile(
        transcription(("8b", "", "\\(l=(-\\infty;-1]\\); \\(L=[1;+\\infty)\\)", True, "clear")),
        transcription(("8b", "", "\\ell = (-\\infty;-1]; L = [1;+\\infty)", True, "clear")))
    assert note is None


def test_a_shared_part_that_differs_is_still_a_disagreement():
    [(_, note)] = grading.reconcile(transcription(("8b", "", "inf = -1; sup = 1", True, "clear")),
                                    transcription(("8b", "", "inf = -1; sup = 1/2; max = 1/2", True, "clear")))
    assert note and "disagree" in note


def test_a_blank_problem_missing_from_the_other_reading_is_not_flagged():
    [(_, note)] = grading.reconcile(transcription(("12", "", "", False, "clear")), transcription())
    assert note is None


def test_bracketed_labels_match_plain_ones():
    assert grading.normalize_label("(8)a)") == grading.normalize_label("8a") == grading.normalize_label("8 a)")


def test_each_file_is_decoded_once_per_grading(fake_llm, page, tmp_path, monkeypatch):
    """Both readings and the grader used to decode the same photo and sheet separately,
    at the same time - enough to push a 512 MB Render instance over its memory limit."""
    sheet = tmp_path / "sheet.jpg"
    Image.new("RGB", (300, 400), "white").save(sheet)
    decoded = []
    real_load_pages = grading.load_pages
    monkeypatch.setattr(grading, "load_pages", lambda path: decoded.append(path.name) or real_load_pages(path))
    fake_llm.reply("homework_transcription", transcription(("1", "", "5", True, "clear")))
    fake_llm.reply("homework_grading", graded(("1", "number", "", "5", "5", "5", "correct")))

    grading.grade_submission(page, "S", None, task_file_paths=[sheet])

    assert sorted(decoded) == ["page.jpg", "sheet.jpg"]


def test_grader_never_sees_the_students_pages(fake_llm, page):
    fake_llm.reply("homework_transcription", transcription(("1", "", "5", True, "clear")))
    fake_llm.reply("homework_grading", graded(("1", "number", "", "5", "5", "5", "correct")))

    grading.grade_submission(page, "S", None)

    grading_call = next(c for c in fake_llm.calls if c["kind"] == "homework_grading")
    assert not any(part.get("type") == "image_url" for part in grading_call["messages"][1]["content"])


def test_explanations_are_requested_in_the_students_language(fake_llm, page):
    fake_llm.reply("homework_transcription", transcription(("1", "", "5", True, "clear")))
    fake_llm.reply("homework_grading", graded(("1", "number", "", "5", "5", "5", "correct")))

    grading.grade_submission(page, "S", None, language="ru", curriculum="pt")

    system = next(c for c in fake_llm.calls if c["kind"] == "homework_grading")["messages"][0]["content"]
    assert "in Russian" in system and "Portuguese national curriculum" in system


def test_superseded_grading_job_cannot_overwrite_the_newer_result(monkeypatch):
    """A student resubmitting mid-grading used to get the old photos' result written last."""
    student_id = make_student()
    submission_id = make_submission(make_assignment(student_id), student_id)
    monkeypatch.setattr(grading_jobs, "grade_submission", lambda *a, **k: {"problems": [], "tag": "first"})

    started = []
    monkeypatch.setattr(grading_jobs, "_run_in_background", started.append)
    grading_jobs.start_grading_job(submission_id, [], "S")               # job 1 starts, stalls
    monkeypatch.setattr(grading_jobs, "grade_submission", lambda *a, **k: {"problems": [], "tag": "second"})
    grading_jobs.start_grading_job(submission_id, [], "S")               # student resubmits: job 2
    started[1]()                                                          # job 2 finishes first
    monkeypatch.setattr(grading_jobs, "grade_submission", lambda *a, **k: {"problems": [], "tag": "first"})
    started[0]()                                                          # stale job 1 finishes last

    stored = json.loads(fetch_one("SELECT ai_result FROM student_submissions WHERE id = ?", (submission_id,))["ai_result"])
    assert stored["tag"] == "second"


def test_grading_failure_is_recorded_not_swallowed(monkeypatch):
    student_id = make_student()
    submission_id = make_submission(make_assignment(student_id), student_id)

    def fail(*args, **kwargs):
        raise grading.GradingError("Transcription failed: boom")

    monkeypatch.setattr(grading_jobs, "grade_submission", fail)
    grading_jobs.start_grading_job(submission_id, [], "S")

    row = fetch_one("SELECT ai_status, ai_error FROM student_submissions WHERE id = ?", (submission_id,))
    assert (row["ai_status"], row["ai_error"]) == ("error", "Transcription failed: boom")


def test_llm_errors_surface_as_grading_errors(monkeypatch, page):
    def down(*args, **kwargs):
        raise llm.LLMError("RateLimitError: 429")

    monkeypatch.setattr(llm, "complete", down)
    with pytest.raises(grading.GradingError):
        grading.grade_submission(page, "S", None)
