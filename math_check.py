"""Deterministic answer checking with sympy.

The model's own verdict is a guess; when a problem and the answers can be
parsed as plain math, the result here is exact and overrules it.
"""

import re
from dataclasses import dataclass
from typing import Optional

import sympy
from sympy.parsing.sympy_parser import (convert_xor, implicit_multiplication, parse_expr,
                                        standard_transformations)

MAX_LENGTH = 200
# parse_expr() evaluates Python. The text reaching it is model output derived
# from a student's photo, so prompt injection can put anything here: only
# math characters, single-letter variables and a fixed set of function names
# ever reach the parser.
_SAFE_CHARS = re.compile(r"^[0-9A-Za-z+\-*/^().,=\s]*$")
_FUNCTIONS = {"sqrt": sympy.sqrt, "sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan,
              "log": sympy.log, "ln": sympy.log, "exp": sympy.exp, "abs": sympy.Abs, "pi": sympy.pi}
# implicit_multiplication: models (and people) write 4(2m-1)+3m, not 4*(2*m-1)+3*m; without
# it such an equation didn't parse and the exact check was silently skipped.
_TRANSFORMS = standard_transformations + (convert_xor, implicit_multiplication)
_SPLIT_SOLUTIONS = re.compile(r"\s*(?:,|;|\bor\b|\bou\b|\bили\b)\s*", re.IGNORECASE)
_DECIMAL_COMMA = re.compile(r"(?<=\d),(?=\d)")


def parse(text) -> Optional[sympy.Expr]:
    if not text or len(text) > MAX_LENGTH or not _SAFE_CHARS.match(text) or "=" in text:
        return None
    local_dict = {}
    for name in set(re.findall(r"[A-Za-z]+", text)):
        if name in _FUNCTIONS:
            local_dict[name] = _FUNCTIONS[name]
        elif len(name) == 1:
            local_dict[name] = sympy.Symbol(name)
        else:
            return None
    try:
        result = parse_expr(text, local_dict=local_dict, transformations=_TRANSFORMS)
    except Exception:
        return None
    return result if isinstance(result, sympy.Expr) else None  # "0,5" parses to a tuple


def _parse_number_or_expression(text):
    """Students on the Portuguese and Russian curricula write 2,5 for 2.5."""
    return parse(_DECIMAL_COMMA.sub(".", text)) if text else None


def equivalent(a, b) -> Optional[bool]:
    """True/False when both parse; None when either can't be checked."""
    if a is None or b is None:
        return None
    try:
        difference = sympy.simplify(a - b)
        if difference == 0:
            return True
        result = difference.equals(0)
        return bool(result) if result is not None else None
    except Exception:
        return None


def _parse_solution_set(text):
    if not text:
        return None
    values = []
    for part in _SPLIT_SOLUTIONS.split(text.strip()):
        if not part:
            continue
        part = part.split("=")[-1]
        value = parse(part)
        if value is None:
            return None
        values.append(value)
    return values or None


def _matches_solutions(text, solutions) -> Optional[bool]:
    """Does the written answer give exactly these solutions? "2,5" can mean the number
    2.5 (decimal comma) or the two solutions 2 and 5, so both readings are tried and
    either one matching is a match."""
    readings = {_DECIMAL_COMMA.sub(".", text or ""), text or ""}
    results = [_same_solution_set(_parse_solution_set(reading), solutions) for reading in readings]
    if True in results:
        return True
    return False if False in results else None


def _same_solution_set(a, b) -> Optional[bool]:
    if a is None or b is None:
        return None
    if len(a) != len(b):
        return False
    remaining = list(b)
    for value in a:
        match = next((other for other in remaining if equivalent(value, other)), None)
        if match is None:
            return False
        remaining.remove(match)
    return True


def _solve_equation(problem_expr):
    if not problem_expr or problem_expr.count("=") != 1:
        return None
    left, right = (parse(side) for side in problem_expr.split("="))
    if left is None or right is None:
        return None
    symbols = (left - right).free_symbols
    if len(symbols) != 1:
        return None
    try:
        return list(sympy.solve(sympy.Eq(left, right), symbols.pop()))
    except Exception:
        return None


def _letters(text):
    return sorted(set(re.findall(r"\b([A-H])\b", (text or "").upper())))


def _true_false(text):
    pairs = re.findall(r"\b([A-H])\s*[-:=–)]?\s*(V|F|T|В|Н)\b", (text or "").upper())
    truth = {"V": True, "T": True, "В": True, "F": False, "Н": False}
    return {letter: truth[mark] for letter, mark in pairs} or None


@dataclass
class Check:
    student_matches: Optional[bool] = None
    key_matches: Optional[bool] = None
    reference_latex: Optional[str] = None


def check(kind, problem_expr, correct_expr, student_expr) -> Check:
    """kind: expression | equation | number | choice | true_false | other."""
    if kind == "choice":
        want, got = _letters(correct_expr), _letters(student_expr)
        return Check(student_matches=(want == got) if want and got else None)
    if kind == "true_false":
        want, got = _true_false(correct_expr), _true_false(student_expr)
        return Check(student_matches=(want == got) if want and got else None)

    if kind == "equation":
        solutions = _solve_equation(problem_expr)
        if solutions is None:
            key = _parse_solution_set(_DECIMAL_COMMA.sub(".", correct_expr or ""))
            return Check(student_matches=_matches_solutions(student_expr, key) if key else None)
        reference = ", ".join(sympy.latex(s) for s in solutions) or "\\emptyset"
        return Check(student_matches=_matches_solutions(student_expr, solutions),
                     key_matches=_matches_solutions(correct_expr, solutions),
                     reference_latex=reference)

    if kind in ("expression", "number"):
        problem = parse(problem_expr)
        student = _parse_number_or_expression(student_expr)
        key = _parse_number_or_expression(correct_expr)
        if problem is None:
            return Check(student_matches=equivalent(student, key))
        try:
            reference = sympy.latex(sympy.simplify(problem))
        except Exception:
            reference = None
        return Check(student_matches=equivalent(student, problem),
                     key_matches=equivalent(key, problem),
                     reference_latex=reference)

    return Check()
