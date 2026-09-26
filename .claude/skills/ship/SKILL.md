---
name: ship
description: Commit and release TutorIlya Homework changes to production - pre-flight checks, clean commits, explicit approval before pushing to main (which auto-deploys on Render), then post-deploy checks. Use when the user asks to commit, push, deploy, release, or "make it live".
---

# Ship

Pushing to `main` **is** a production deploy: GitHub Actions CI runs, and when
it's green Render deploys (`autoDeployTrigger: checksPass`). Students use it
immediately.

## 1. Pre-flight

- `git status` / `git diff --stat`: every changed file belongs to this release.
  Nothing from `evals/cases/`, `evals/results/`, `uploads/`, `*.db`, `.env`,
  logs, or scratch scripts. Grep the diff for API keys and passwords.
- `python -m pytest -q` and `ruff check --select F .` - both green (same as CI).
- Prompt/schema/model/image-pipeline changes: `ai-eval` numbers exist for this
  exact code (not an earlier version of the prompt).
- New POST forms have `{{ csrf_field() }}`; new student routes check ownership.
- New columns are in `MIGRATIONS` (additive, with defaults that suit existing rows).
- Touched templates were rendered at least once (EN + RU for student pages).

## 2. Commit

- Split into logical commits (security / bug fix / AI / UI / tests / docs), each
  one coherent. Message style of this repo: short imperative sentence that says
  what changes for the user ("Stop the AI from grading placeholder answers as
  correct"), body for the why if not obvious.
- Commit only; never `--no-verify`, never amend published commits.

## 3. Ask before pushing

Tell the user, in plain words:
- what changes for students and for the tutor;
- database migrations that will run on the live DB;
- AI behaviour changes and their eval numbers;
- Render settings they must change themselves (env vars etc.) and whether
  before or after the deploy;
- how to roll back (Render "rollback to previous deploy", or revert commit).

Then wait for an explicit "yes, push". Approval for one push doesn't cover
the next.

## 4. After the push

- CI: `gh run list --limit 3` / `gh run watch` (or ask the user to check the
  Actions tab). If CI fails, nothing deploys - fix forward with a new commit.
- If Render tools are loaded: watch the deploy to `live`, read startup logs for
  tracebacks/migration errors. Otherwise ask the user to check the Render
  dashboard.
- `https://homework.tutorilya.com/healthz` returns `ok`.
- Smoke check https://homework.tutorilya.com: login page loads, `/me/login`
  loads. Don't log in with the user's credentials - ask them to click through
  the flows that changed.
- Report: commits pushed, deploy status, what was checked, what the user
  should still check by hand.
