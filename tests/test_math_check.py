import pytest

import math_check


def test_detects_a_wrong_answer_key_from_production():
    # Real case: the AI answered "0" for x/(y-1) + 5/(1-y) and marked the student correct.
    result = math_check.check("expression", "x/(y-1)+5/(1-y)", "0", "(x-5)/(y-1)")
    assert result.key_matches is False
    assert result.student_matches is True
    assert result.reference_latex == "\\frac{x - 5}{y - 1}"


def test_catches_a_dropped_cross_term():
    # Real case: the AI's key for (a-b)^2/(2a) + b kept a stray 2ab.
    result = math_check.check("expression", "(a-b)^2/(2*a)+b", "(a^2-b^2+2*a*b)/(2*a)", "(a^2+b^2)/(2*a)")
    assert (result.key_matches, result.student_matches) == (False, True)


def test_equation_solutions_compared_as_sets():
    result = math_check.check("equation", "x^2-5*x+6=0", "2, 3", "x=3 ou x=2")
    assert (result.key_matches, result.student_matches) == (True, True)


def test_wrong_equation_solution():
    assert math_check.check("equation", "2*x+1=7", "3", "4").student_matches is False


def test_arithmetic_is_recomputed():
    # Real case: the student's 180-(56+90)=34 was misread and marked wrong.
    assert math_check.check("number", "180-(56+90)", "34", "34").student_matches is True


def test_multiple_choice_and_true_false():
    assert math_check.check("choice", "", "D", "B").student_matches is False
    assert math_check.check("choice", "", "D", "d").student_matches is True
    tf = math_check.check("true_false", "", "A V; B F; C F; F V", "A-V, B-F, C-F, F-V")
    assert tf.student_matches is True


def test_equations_written_the_way_people_write_them_are_checked():
    # Real case: the model wrote 4(2m-1)+3m, the parser wanted 4*(2*m-1)+3*m, the check was
    # silently skipped and gpt-4o's wrong key (-1) reached the tutor. The true solution is 0.
    result = math_check.check("equation", "4(2m-1)+3m = 2(4m-1)-(2-m)", "-1", "0.4")
    assert (result.reference_latex, result.key_matches, result.student_matches) == ("0", False, False)
    assert math_check.equivalent(math_check.parse("3(x+1)+2(2x-3)"), math_check.parse("7*x-3")) is True


def test_a_decimal_comma_is_one_number_not_two_solutions():
    # Portuguese and Russian students write 2,5 - it was read as the solutions 2 and 5.
    assert math_check.check("equation", "2*x=5", "2.5", "x=2,5").student_matches is True
    assert math_check.check("equation", "5*m=-2", "-0.4", "0,4").student_matches is False
    assert math_check.check("number", "1/4+1/4", "0.5", "0,5").student_matches is True
    # ...while "2,3" for a quadratic still means two solutions
    assert math_check.check("equation", "x^2-5*x+6=0", "2, 3", "2,3").student_matches is True


def test_values_the_sheet_gives_are_not_mistaken_for_a_wrong_key():
    """Real case ("Sabendo que log2 a = 5, determina log2(√2·a)"): the expression still
    contains a, the key 11/2 doesn't, so the check called the key wrong, replaced it
    with log(a)/log(2) + 1/2 and failed the student's correct 11/2."""
    result = math_check.check("number", "ln(2^(1/2)*a)/ln(2)", "11/2", "11/2")
    assert (result.student_matches, result.key_matches, result.reference_latex) == (True, None, None)
    assert math_check.check("number", "ln(x^2*y)/ln(10)", "7", "7").student_matches is True
    # "log2 9 = x - write log2 64 - log2 27 in terms of x": the key brings in x
    assert math_check.check("expression", "ln(64)/ln(2)-ln(27)/ln(2)", "6-3*x/2", "6-3*x/2").student_matches is True
    wrong = math_check.check("expression", "ln(6)/ln(2)", "1+x/2", "x/2")
    assert (wrong.student_matches, wrong.key_matches) == (False, None)


def test_log_identities_that_need_positive_arguments_are_recognised():
    """Real case: ln(x²-y²) - 2ln(√(x-y)) = ln(x+y) for x > y > 0, but sympy can't
    simplify it without knowing the signs - the right key was "corrected" into the
    unsimplified expression and its explanation deleted."""
    result = math_check.check("expression", "ln(x^2-y^2)-2*ln((x-y)^(1/2))", "ln(x+y)",
                              "ln(x^2-y^2)/ln(abs(x-y))")
    assert (result.key_matches, result.student_matches) == (True, False)
    assert result.reference_latex == "\\log{\\left(x + y \\right)}"


def test_a_log_without_a_base_is_not_guessed():
    # school "log" is base 10, sympy's is base e: log(100) = 2 was "checked" as 2·ln(10)
    assert math_check.parse("log(100)") is None
    assert math_check.check("number", "log(100)", "2", "2").student_matches is True


def test_one_of_several_true_options_is_left_to_the_grader():
    """Real case: a flawed multiple-choice question had three true options; the key
    listed all three, the student chose one of them and was marked incorrect."""
    assert math_check.check("choice", "", "B; C; D", "C").student_matches is None
    assert math_check.check("choice", "", "B; C; D", "A").student_matches is False


def test_unparseable_input_gives_no_opinion():
    assert math_check.check("expression", "\\frac{x}{y}", "", "").student_matches is None
    assert math_check.check("proof", "", "", "").student_matches is None


@pytest.mark.parametrize("hostile", [
    '__import__("os").system("x")', "exec(1)", "eval(1)", "a.__class__", "lambda: 1", "open(1)",
    "xy+1",  # multi-letter names are rejected outright - the model must write x*y
])
def test_parser_never_evaluates_arbitrary_names(hostile):
    assert math_check.parse(hostile) is None
