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


def test_an_explanation_built_on_a_wrong_key_is_not_shown_to_the_student(fake_llm, page):
    """gpt-4o told the student "the correct value of m is -1" for an equation whose
    solution is 0; the verdict (incorrect) was right, the explanation was not."""
    fake_llm.reply("homework_transcription",
                   transcription(("6", "4(2m-1)+3m=2(4m-1)-(2-m)", "m=0,4", True, "clear")))
    fake_llm.reply("homework_grading", graded(
        ("6", "equation", "4(2m-1)+3m = 2(4m-1)-(2-m)", "-1", "0.4", "-1", "incorrect")))

    result = grading.grade_submission(page, "S", None, task_file_paths=page)

    problem = result["problems"][0]
    assert (problem["verdict"], problem["correct_answer"], problem["explanation"]) == ("incorrect", "\\(0\\)", "")
    assert any("answer key was wrong" in flag and "explanation" in flag for flag in result["flags_for_tutor"])


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
    assert note and "sup" in note


def test_one_unclear_part_does_not_throw_away_the_whole_problem(fake_llm, page):
    """A student who crosses out and rewrites got every multi-part problem marked
    "unclear" because the two readings rendered one struck-out part differently."""
    fake_llm.reply("homework_transcription",
                   transcription(("8b", "", "l = (-\\infty;-1]; L = [1;+\\infty); sup = 1; max = 1", True, "clear")),
                   transcription(("8b", "", "l = (-\\infty;-1]; L = (1;+\\infty); sup = 1; max = 1", True, "clear")))
    fake_llm.reply("homework_grading", graded(("8b", "text", "", "", "", "sup = 1/2", "partially_correct")))

    result = grading.grade_submission(page, "S", None, task_file_paths=page)

    problem = result["problems"][0]
    assert problem["verdict"] == "partially_correct" and problem["confidence"] == "low"
    [flag] = [f for f in result["flags_for_tutor"] if f.startswith("8b")]
    assert "L" in flag and "sup" not in flag and len(flag) < 160
    sent = json.dumps(next(c for c in fake_llm.calls if c["kind"] == "homework_grading")["messages"])
    assert "read_two_ways" in sent and "L: [1;+" in sent and "/ (1;+" in sent


def test_crossed_out_markers_in_any_spelling_are_ignored():
    for struck in ("\\cancel{\\varnothing} 1", "[\\text{crossed out}] 1", "\\sout{0} 1"):
        [(_, note)] = grading.reconcile(transcription(("8a", "", f"inf = 0; max = {struck}", True, "clear")),
                                        transcription(("8a", "", "inf = 0; max = 1", True, "clear")))
        assert note is None, struck


def test_a_blank_problem_missing_from_the_other_reading_is_not_flagged():
    [(_, note)] = grading.reconcile(transcription(("12", "", "", False, "clear")), transcription())
    assert note is None


def test_unnumbered_problems_are_each_read_and_graded_on_their_own(fake_llm, page):
    """A sheet whose first equations carry no numbers: every problem had the label "",
    so all of them were compared with - and graded as - the last one ("x=2 vs x=7")."""
    reading = transcription(("", "2x-2=12-5x", "x=2", True, "clear"),
                            ("", "7y-10=y+50", "y=10", True, "clear"),
                            ("", "2(x-1)+3(x+1)=4(x+2)", "x=7", True, "clear"),
                            ("b)", "x/3=5", "x=15", True, "clear"))
    fake_llm.reply("homework_transcription", reading)
    fake_llm.reply("homework_grading", graded(
        ("#1", "equation", "2*x-2=12-5*x", "2", "2", "x=2", "correct"),
        ("#2", "equation", "7*y-10=y+50", "10", "10", "y=10", "correct"),
        ("#3", "equation", "2*(x-1)+3*(x+1)=4*(x+2)", "7", "7", "x=7", "correct"),
        ("b)", "equation", "x/3=5", "15", "15", "x=15", "correct")))

    result = grading.grade_submission(page, "S", None, task_file_paths=page)

    assert [p["problem_label"] for p in result["problems"]] == ["#1", "#2", "#3", "b)"]
    assert [p["verdict"] for p in result["problems"]] == ["correct"] * 4
    assert [p["student_answer"] for p in result["problems"]] == ["x=2", "y=10", "x=7", "x=15"]
    assert not any("disagree" in flag for flag in result["flags_for_tutor"])
    sent = json.dumps(next(c for c in fake_llm.calls if c["kind"] == "homework_grading")["messages"])
    assert "#1" in sent and "#3" in sent


@pytest.mark.parametrize("label, cleaned", [
    ("2x - 2 = 12 - 5x", ""),                     # the model used the equation as the label
    ("\\(7y - 10 = y + 50\\)", ""),
    ("b) \\frac{x}{3} = 5", "b)"),                # letter + the equation: keep the letter
    ("(8) a)", "(8) a)"), ("9a", "9a"), ("10.2", "10.2"), ("№58 а)", "№58 а)"), ("", ""), ("?", ""),
    ("1.1.", "1.1"), ("4.", "4"),                 # gpt-6.1-sol ends printed numbers with a dot
])
def test_a_label_is_only_the_printed_number_or_letter(label, cleaned):
    assert grading.clean_label(label) == cleaned


def test_equations_used_as_labels_are_numbered_like_unlabelled_problems(fake_llm, page):
    fake_llm.reply("homework_transcription",
                   transcription(("2x - 2 = 12 - 5x", "2x-2=12-5x", "x=2", True, "clear"),
                                 ("b) \\frac{x}{3} = 5", "x/3=5", "x=15", True, "clear")),
                   transcription(("", "2x-2=12-5x", "x=2", True, "clear"),
                                 ("b)", "x/3=5", "x=15", True, "clear")))
    fake_llm.reply("homework_grading", graded(("#1", "equation", "2*x-2=12-5*x", "2", "2", "x=2", "correct"),
                                              ("b)", "equation", "x/3=5", "15", "15", "x=15", "correct")))

    result = grading.grade_submission(page, "S", None, task_file_paths=page)

    assert [p["problem_label"] for p in result["problems"]] == ["#1", "b)"]
    assert not any("disagree" in f or "only one" in f for f in result["flags_for_tutor"])


def test_unnumbered_problems_are_paired_by_their_text_even_in_another_order():
    first = transcription(("", "2x-2=12-5x", "x=2", True, "clear"), ("", "7y-10=y+50", "y=10", True, "clear"))
    second = transcription(("", "7y - 10 = y + 50", "y=10", True, "clear"), ("", "2x - 2 = 12 - 5x", "x=2", True, "clear"))
    assert [note for _, note in grading.reconcile(first, second)] == [None, None]


def test_repeated_labels_do_not_collide_either(fake_llm, page):
    reading = transcription(("a)", "x+1=2", "x=1", True, "clear"), ("a)", "x+2=5", "x=3", True, "clear"))
    fake_llm.reply("homework_transcription", reading)
    fake_llm.reply("homework_grading", graded(("a) #1", "equation", "x+1=2", "1", "1", "1", "correct"),
                                              ("a) #2", "equation", "x+2=5", "3", "3", "3", "correct")))

    result = grading.grade_submission(page, "S", None, task_file_paths=page)

    assert [p["problem_label"] for p in result["problems"]] == ["a) #1", "a) #2"]
    assert [p["verdict"] for p in result["problems"]] == ["correct", "correct"]


def test_a_misread_variable_letter_is_not_a_disagreement():
    """Handwritten m read once as x: "x = 0,4" vs "m = 0,4" is the same answer."""
    [(_, same)] = grading.reconcile(transcription(("6", "", "\\(x = 0,4\\)", True, "clear")),
                                    transcription(("6", "", "m = 0,4", True, "clear")))
    [(_, different)] = grading.reconcile(transcription(("6", "", "x = 0,4", True, "clear")),
                                         transcription(("6", "", "x = -0,4", True, "clear")))
    assert same is None and different is not None


def test_bracketed_labels_match_plain_ones():
    assert grading.normalize_label("(8)a)") == grading.normalize_label("8a") == grading.normalize_label("8 a)")
    assert grading.normalize_label("1.1.") == grading.normalize_label("1.1")


@pytest.mark.parametrize("first, second", [
    ("\\(1\\times\\frac{x}{2}\\)", "\\(1\\times\\frac x2\\)"),
    ("\\(\\log\\frac{\\sqrt{y}}{x}\\)", "\\(\\log\\frac{\\sqrt y}{x}\\)"),
    ("C.S. \\(\\{-15\\}\\)", "\\(C.S=\\{-15\\}\\)"),
    ("C.S. \\(=5\\)", "\\(C.S=5\\)"),
    ("convergent; sum = \\(2\\)", "convergent; \\(\\sum\\frac{1}{1-\\frac12}=2\\)"),
    ("divergent; sum = \\(-\\frac3{11}\\)", "divergent; Sum \\(=\\frac{a}{1-r}=\\frac{3}{1-12}=-\\frac{3}{11}\\)"),
    ("series is convergent in \\((-\\frac12;+\\infty)\\)",
     "\\((-\\infty;-1)\\cup(-\\frac12;+\\infty)\\cap(-1;+\\infty)=(-\\frac12;+\\infty)\\); "
     "series is convergent in \\((-\\frac12;+\\infty)\\)"),
])
def test_two_spellings_of_the_same_answer_are_one_reading(first, second):
    """Real readings (gpt-6.1-sol): both copied the page faithfully but wrote \\frac x2 /
    \\frac{x}{2}, "C.S." with or without "=", or kept the work line in front of the
    result - and every such problem was marked "unclear" for the tutor to check."""
    [(_, note)] = grading.reconcile(transcription(("1", "", first, True, "clear")),
                                    transcription(("1", "", second, True, "clear")))
    assert note is None


@pytest.mark.parametrize("first, second", [
    ("C.S. \\(\\{4\\}\\)", "\\(C.S=\\{-4\\}\\)"),
    ("\\(\\frac{1}{-300}\\)", "\\(\\frac{1}{300}\\)"),
    ("\\(\\left(\\frac{9}{2}\\right)^5\\)", "\\(\\left(\\frac{9}{2}\\right)^9\\)"),
    ("180-146=34", "180-136=34"),       # same result, but a step was read two ways
    ("3x = 6", "x = 6"),
])
def test_a_different_value_is_still_a_disagreement(first, second):
    [(_, note)] = grading.reconcile(transcription(("1", "", first, True, "clear")),
                                    transcription(("1", "", second, True, "clear")))
    assert note is not None


@pytest.mark.parametrize("kind, student_expr", [("text", ""), ("choice", "B")])
def test_a_different_option_letter_is_never_correct(fake_llm, page, kind, student_expr):
    """Real case (gpt-4o): the student chose D, the grader's own work gave B, and the
    verdict was "correct" with high confidence. The exact check compares the grader's
    restatement of the answers, so it stayed silent when the grader called the question
    "text" or copied the student's choice as B."""
    fake_llm.reply("homework_transcription",
                   transcription(("6", "Σ 6(-1/4)^n: A) diverges B) -6/5 C) 6/5 D) none", "D", True, "clear")))
    fake_llm.reply("homework_grading", graded(("6", kind, "", "B", student_expr, "B", "correct")))

    result = grading.grade_submission(page, "S", None, task_file_paths=page)

    assert result["problems"][0]["verdict"] == "incorrect"
    assert any(flag.startswith("6:") and "D" in flag and "B" in flag for flag in result["flags_for_tutor"])


def test_the_same_option_in_another_case_stays_correct(fake_llm, page):
    fake_llm.reply("homework_transcription", transcription(("9", "a) 0,25 b) 0,045 c) 0,35", "c", True, "clear")))
    fake_llm.reply("homework_grading", graded(("9", "choice", "", "C", "c", "c) 0,35", "correct")))

    assert grading.grade_submission(page, "S", None, task_file_paths=page)["problems"][0]["verdict"] == "correct"


def test_an_answer_from_values_the_sheet_gives_stays_correct(fake_llm, page):
    """Real case: "Sabendo que log2 a = 5, determina log2(√2·a)". The student's 11/2 was
    right and so was the AI's key, but the exact check didn't know a = 32: it replaced
    the key with a formula in a and marked the student incorrect."""
    fake_llm.reply("homework_transcription", transcription(("1.1", "log2(√2 a)", "\\(\\frac{11}{2}\\)", True, "clear")))
    fake_llm.reply("homework_grading", graded(
        ("1.1", "number", "ln(2^(1/2)*a)/ln(2)", "11/2", "11/2", "11/2", "correct")))

    result = grading.grade_submission(page, "S", None, task_file_paths=page)

    problem = result["problems"][0]
    assert (problem["verdict"], problem["correct_answer"]) == ("correct", "11/2")
    assert not any("answer key was wrong" in flag for flag in result["flags_for_tutor"])


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
