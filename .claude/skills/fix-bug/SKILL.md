---
name: fix-bug
description: Fix a reported or discovered bug in TutorIlya Homework - reproduce it with a failing test first, fix the root cause, keep the test as a regression guard. Use for any "X is broken / wrong / doesn't work" that is reproducible locally. For live production outages, start with debug-production.
---

# Fix a bug

1. **Pin down the symptom.** Exact steps, which user (student/tutor), language,
   expected vs actual. If it's from production and not reproducible locally,
   switch to `debug-production`.

2. **Reproduce it as a failing test** before touching the code.
   - Route/permission/state bugs: `client` + helpers in `tests/conftest.py`
     (`make_student`, `make_assignment`, `make_submission`, `post` adds CSRF,
     `fetch_one` reads the DB). Put it in the matching `tests/test_*.py`.
   - AI pipeline logic: `fake_llm.reply("<schema name>", {...})` feeds canned
     model output - test what the code does with it.
   - Race/background bugs: patch `_run_in_background` to capture the callables
     and run them in the problematic order (see the superseded-job test).
   - Run `python -m pytest -q tests/test_<file>.py -k <name>` and **see it fail
     for the reported reason**. A test that passes before the fix proves nothing.
   - If it truly can't be a test (CSS, iOS picker, model wording), write down
     the manual reproduction and use the browser / `ai-eval` instead.

3. **Find the root cause**, not the nearest symptom. Search for other places
   with the same pattern (same query, same missing ownership check, same
   template habit) - fix them in the same change if they're the same bug.

4. **Fix minimally.** No refactors or unrelated cleanup in the diff. Schema
   changes only via additive `MIGRATIONS`.

5. **Verify.**
   - the new test passes; `python -m pytest -q` is fully green;
   - the original user-visible flow works (browser for UI; EN + RU if student-facing);
   - if the fix touches prompts/models, run `ai-eval` before and after.

6. **Report**: symptom, root cause, fix, regression test name, anything left
   unverified. Don't push - use `ship` when the user wants it live.

Name the test after the behaviour, with a docstring saying what used to go
wrong, e.g. `test_superseded_grading_job_cannot_overwrite_the_newer_result`.
