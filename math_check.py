"""Deterministic answer checking with sympy.

The model's own verdict is a guess; when a problem and the answers can be
parsed as plain math, the result here is exact and overrules it.
"""

import re
from dataclasses import dataclass
from typing import Optional

import sympy
from sympy.parsing.sympy_parser import convert_xor, parse_expr, standard_transformations

MAX_LENGTH = 200
# parse_expr() evaluates Python. The text reaching it is model output derived
# from a student's photo, so prompt injection can put anything here: only
# math characters, single-letter variables and a fixed set of function names
# ever reach the parser.
_SAFE_CHARS = re.compile(r"^[0-9A-Za-z+\-*/^().,=\s]*$")
_FUNCTIONS = {"sqrt": sympy.sqrt, "sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan,
              "log": sympy.log, "ln": sympy.log, "exp": sympy.exp, "abs": sympy.Abs, "pi": sympy.pi}
_TRANSFORMS = standard_transformations + (convert_xor,)
_SPLIT_SOLUTIONS = re.compile(r"\s*(?:,|;|\bor\b|\bou\b|\bили\b)\s*", re.IGNORECASE)


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
        return parse_expr(text, local_dict=local_dict, transformations=_TRANSFORMS)
    except Exception:
        return None


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
        student = _parse_solution_set(student_expr)
        key = _parse_solution_set(correct_expr)
        if solutions is None:
            return Check(student_matches=_same_solution_set(student, key))
        reference = ", ".join(sympy.latex(s) for s in solutions) or "\\emptyset"
        return Check(student_matches=_same_solution_set(student, solutions),
                     key_matches=_same_solution_set(key, solutions),
                     reference_latex=reference)

    if kind in ("expression", "number"):
        problem = parse(problem_expr)
        student = parse(student_expr)
        key = parse(correct_expr)
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
