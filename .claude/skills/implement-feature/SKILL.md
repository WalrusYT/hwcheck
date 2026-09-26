---
name: implement-feature
description: Plan and implement a new feature or behaviour change in TutorIlya Homework safely - inspect first, plan, build the smallest coherent change with tests, then hand over to verify-feature.
---

# Implement a feature

## 1. Understand before editing

Read the routes, templates, `db.py` schema, and modules involved. Restate the
requested behaviour in a few lines and list what it touches:

- tables/columns (new ones -> additive entry in `db.MIGRATIONS`, default that
  suits existing production rows);
- routes and who may call them (admin / which student - ownership checks);
- templates (EN + RU strings via `translations.py`, mobile layout);
- notifications (created in the state-changing request, recipient's language);
- uploaded files (listed on the DB row, cleaned up on delete);
- AI behaviour (prompts, schemas, models - requires `ai-eval`);
- production (env vars, disk paths, the single gunicorn worker).

For anything larger than a small change, or when business rules are unclear,
show the plan to the user and wait.

## 2. Build

- Follow the structure in `CLAUDE.md` "Code structure": thin routes, logic in
  the module that owns the concept, OpenAI only via `llm.py`, slow work via a
  `_run_in_background` seam.
- Reuse existing helpers (`auth`, `image_utils`, `math_check`, `get_db`,
  `csrf_field`) instead of writing new ones.
- Every new POST form: `{{ csrf_field() }}`. JS POSTs: `X-CSRF-Token` header.
- No new dependency unless the stdlib and current deps can't do it; if added,
  pin the exact version in `requirements.txt`.
- No unrelated refactors in the same diff.

## 3. Test as you go

- Add tests in `tests/` for the new behaviour and its failure paths:
  permissions (the other student gets 404/redirect), invalid input, AI failure
  (`fake_llm` raising or returning junk).
- `python -m pytest -q` green before handing over.
- Run the app (`python app.py`, port 5050) and click through the flow.

## 4. Hand over

Run the `verify-feature` skill. Do not commit or push unless asked; releasing
goes through `ship`.
