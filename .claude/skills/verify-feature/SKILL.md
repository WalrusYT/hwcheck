---
name: verify-feature
description: Verify a finished TutorIlya Homework change before calling it ready - diff review, tests, authorization, browser flow in EN/RU and mobile, AI and failure paths - and report exactly what was and wasn't verified.
---

# Verify a feature

"It imports", "the page rendered once", and "tests pass" are not verification.
Pick the layers below that the change actually touches and check them.

If verification finds a bug caused by this change and the fix is small and
clear, fix it and re-check. Otherwise report it. Stop and explain first if it
is a security or data-loss problem.

## 1. Diff review

`git diff` / `git status`: only intended files; no debug prints, commented-out
code, secrets, real student data, stray scratch files; no unrelated refactors.

## 2. Automated checks

- `python -m pytest -q` - all green. Add missing tests for the new behaviour
  rather than skipping this.
- AI changes: `ai-eval` before/after numbers for this exact code.

## 3. Data

- New columns/tables come from `db.MIGRATIONS` and apply cleanly to an existing
  DB (start the app against a copy of a populated local `hwcheck.db`).
- Writes persist; no duplicate rows on double-submit or refresh; GET requests
  change nothing.
- Deletes: every related table and file handled, nothing still-referenced removed.

## 4. Authorization

For every touched route, test server-side (test client or HTTP), not by
hiding buttons:
- logged-out -> redirect to login; student -> no admin route;
- student A can't read or change student B's assignment, submission, files,
  grade, chat, notifications (object-ID / IDOR check);
- POST without a CSRF token -> 400.

## 5. Browser flow

Run `python app.py` and use the flow the change affects - not the whole product
unless the change is broad. Full loop for broad homework changes: admin creates
student and assignment -> student logs in, opens it, uses hints, submits several
files -> AI draft appears for the tutor -> tutor edits and publishes -> student
gets the notification, sees grade and comment -> performance page and PDF update.

Check the state transitions and error messages, not just that pages load.

## 6. Student-facing extras

- **EN and RU**: labels, errors, statuses, notifications, AI replies. No new
  hardcoded strings. Notifications use the recipient's saved language.
- **Mobile** (browser `resize_window` preset mobile): homework detail, upload
  widget, feedback, nav - no horizontal overflow, buttons reachable.
- **Uploads**: multiple files, add more, remove one, the submitted list matches
  the UI, PDFs still work, no `capture` attribute.
- Real iPhone picker/camera behaviour can't be verified in emulation - list it
  as a manual check.

## 7. AI features

- Grading: correct files and context sent; tutor review still mandatory; the
  submission stays usable when the model errors or returns junk (tests with
  `fake_llm`); results land on the right submission.
- Hint chat: `python evals/run_chat_eval.py` - language, register, length, no
  answer leaks, injection probes; coin refunded on failure.
- Narrative: correct student's grades only, their language, refreshed after a
  grade change, old text kept on failure.

## 8. Production assumptions

Env var names, `DATA_DIR`, disk paths, Python version, single worker. Inspect
Render read-only if the tools are loaded; never change production config here.

## 9. Report

```
### Verified
- <check> - <how: pytest / local browser / HTTP / eval numbers>
### Bugs found and fixed
### Existing issues discovered   (severity, file, why it matters)
### Not verified                 (iPhone, production config, ...)
### Status: Ready for manual review | Ready to deploy | Blocked
```

Never "Ready to deploy" with a known high-severity issue open. Never say
"works on iPhone" or "production verified" from local checks.
