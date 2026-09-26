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


def test_unparseable_input_gives_no_opinion():
    assert math_check.check("expression", "\\frac{x}{y}", "", "").student_matches is None
    assert math_check.check("proof", "", "", "").student_matches is None


@pytest.mark.parametrize("hostile", [
    '__import__("os").system("x")', "exec(1)", "eval(1)", "a.__class__", "lambda: 1", "open(1)",
    "xy+1",  # multi-letter names are rejected outright - the model must write x*y
])
def test_parser_never_evaluates_arbitrary_names(hostile):
    assert math_check.parse(hostile) is None
