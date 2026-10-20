"""Deterministic answer checking with sympy.

The model's own verdict is a guess; when a problem and the answers can be
parsed as plain math, the result here is exact and overrules it.
"""

import random
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
# No "log": at school it is base 10, in sympy base e, so log(100) = 2 was "checked"
# against 2*ln(10). The grader writes ln(x) and ln(x)/ln(b); an expression with a bare
# log isn't checked at all.
_FUNCTIONS = {"sqrt": sympy.sqrt, "sin": sympy.sin, "cos": sympy.cos, "tan": sympy.tan,
              "ln": sympy.log, "exp": sympy.exp, "abs": sympy.Abs, "pi": sympy.pi}
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
    except Exception:
        result = None
    if result is not True:
        # ln(x²-y²) - ln(x-y) = ln(x+y) holds wherever both sides are defined, but sympy
        # won't simplify it without knowing the signs - so compare values at real points.
        numeric = _equal_at_sample_points(a, b)
        if numeric is not None:
            return numeric
    return bool(result) if result is not None else None


def _equal_at_sample_points(a, b, tries=60, needed=6) -> Optional[bool]:
    """True when a and b agree at `needed` random points where both are real; False at
    the first real point where they differ; None when too few such points were found."""
    symbols = sorted(a.free_symbols | b.free_symbols, key=str)
    if not symbols:
        return None
    rng = random.Random(0)  # same points every run: a verdict must not flicker
    agreed = 0
    for _ in range(tries):
        point = {s: sympy.Rational(rng.randint(-500, 500), 100) for s in symbols}
        try:
            va, vb = complex(a.evalf(subs=point)), complex(b.evalf(subs=point))
        except (TypeError, ValueError, ZeroDivisionError):
            continue
        if abs(va.imag) > 1e-12 or abs(vb.imag) > 1e-12 or not all(map(_finite, (va.real, vb.real))):
            continue
        if abs(va.real - vb.real) > 1e-9 * max(1.0, abs(va.real)):
            return False
        agreed += 1
        if agreed >= needed:
            return True
    return None


def _finite(value):
    return value == value and abs(value) != float("inf")


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
        if not (want and got) or want == got:
            return Check(student_matches=True if want and got else None)
        # One of several right letters: a question with more than one true option (or a
        # multi-select left incomplete) - which it is, only the grader can tell.
        return Check(student_matches=False if set(got) - set(want) else None)
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
        reference = _simplest(problem)
        substituted = key is not None and bool(key.free_symbols - reference.free_symbols)
        if substituted or (kind == "number" and reference.free_symbols):
            # The answer depends on something the expression doesn't carry: a substitution
            # ("log2 9 = x - write it in terms of x") or values the sheet gives elsewhere (a
            # number answer to an expression in a: "log2 a = 5"). The expression alone
            # can't judge the key; only key and student can be compared.
            return Check(student_matches=equivalent(student, key))
        return Check(student_matches=equivalent(student, problem),
                     key_matches=equivalent(key, problem),
                     reference_latex=sympy.latex(reference))

    return Check()


def _simplest(expr):
    """The expression as a key a student would write. simplify() leaves
    ln(x²-y²) - ln(x-y) alone (it can't know x > y > 0); combining the logs gives
    ln(x+y) - unless that form is worse, e.g. ln(a)/ln(2) turning into a power of
    1/ln(2)."""
    try:
        simplest = sympy.simplify(expr)
    except Exception:
        return expr
    if expr.has(sympy.log):
        try:
            combined = sympy.simplify(sympy.logcombine(expr, force=True))
        except Exception:
            combined = None
        if (combined is not None and sympy.count_ops(combined) < sympy.count_ops(simplest)
                and not any(power.exp.has(sympy.log) for power in combined.atoms(sympy.Pow))):
            simplest = combined
    return simplest
