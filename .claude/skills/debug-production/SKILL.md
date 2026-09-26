---
name: debug-production
description: Diagnose production failures using evidence-driven root-cause analysis
---

Diagnose the issue before changing code.

Do not make speculative fixes.

## TutorIlya specifics

- Service: Render web service `hwcheck`, deployed from `main`, disk
  `hwcheck-data` at `/var/data` (`DATA_DIR`), one gunicorn worker.
- Env vars: `OPENAI_API_KEY`, `ADMIN_PASSWORD`, `FLASK_SECRET_KEY`,
  `OPENAI_MODEL`, optional `OPENAI_TRANSCRIBE_MODEL` / `OPENAI_GRADE_MODEL`.
  Production mode requires `RENDER=true` (set by Render) and a secret key.
- AI failures surface as `LLMError` from `llm.py`; grading stores them in
  `student_submissions.ai_status='error'` / `ai_error` - query those first.
- Grading jobs still `pending` at a restart/deploy are marked interrupted by
  the startup sweep in `app.py` (the tutor re-runs them); a job
  whose `ai_job_id` no longer matches was superseded by a resubmission and its
  result is dropped on purpose.
- Rate-limited logins are rows in `login_attempts` (per IP, 15 min window).
- If the Render MCP tools aren't loaded in the session, ask the user to enable
  the Render connector (or paste the log lines) instead of guessing.
- Once the cause is found and reproducible locally, finish with the `fix-bug`
  skill so the fix gets a regression test.

## Process

1. Reproduce or precisely characterize the failure.

Collect:

- exact error;
- affected feature;
- first known occurrence;
- whether local and production behavior differ;
- whether recent deploy/config changes exist.

2. Identify the failing layer.

Possible layers include:

- browser/UI;
- Flask route;
- application logic;
- database;
- filesystem/persistent disk;
- external API;
- HTTP client;
- environment/configuration;
- deployment infrastructure.

3. Generate multiple plausible hypotheses.

Do not commit to the first explanation.

4. Test hypotheses in order of information gain and cost.

Prefer isolated tests before modifying production code.

Examples:

- test database access independently;
- inspect sanitized environment-variable properties;
- reproduce API call using the same HTTP library;
- test raw connectivity separately from application logic;
- compare local vs production behavior.

5. Identify root cause.

Clearly distinguish:

- root cause;
- symptoms;
- contributing factors.

6. Implement the smallest appropriate fix.

Do not refactor unrelated components during incident response.

7. Prevent recurrence.

Where practical:

- add validation;
- add regression test;
- improve logging;
- document configuration requirement;
- add startup checks.

## Security

Never print complete:

- passwords;
- API keys;
- Authorization headers;
- session secrets.

When checking environment variables, inspect safe properties such as:

- existence;
- length;
- leading/trailing whitespace;
- newline presence.

## Final report

Summarize:

- symptoms;
- hypotheses tested;
- evidence;
- root cause;
- fix;
- regression protection.

## Render production diagnostics

This application is deployed on Render.

When the Render MCP tools are available, use them as part of production diagnosis instead of asking the user to manually copy information from the Render Dashboard.

Start with read-only inspection.

### 1. Identify the production service

Determine:

- service name and ID;
- currently deployed commit;
- deployment status;
- runtime;
- region;
- relevant project/environment;
- whether a persistent disk is attached;
- current service health where available.

Do not assume the service configuration from local files alone when Render can provide the deployed state.

### 2. Check recent events and deploy history

Inspect recent deploys and relevant service events.

Determine:

- when the problem first appeared;
- whether it correlates with a deploy;
- which commit is currently live;
- whether the latest deploy succeeded;
- whether build and runtime failures are being confused;
- whether configuration changed around the same time.

Compare the currently deployed commit with the local repository when useful.

### 3. Inspect the correct logs

Distinguish between:

- build/deploy logs;
- runtime/application logs;
- request logs where available.

Search around the failure timestamp first.

Look for:

- tracebacks;
- HTTP 4xx/5xx responses;
- application startup failures;
- OpenAI/API errors;
- filesystem errors;
- SQLite errors;
- permission failures;
- missing environment variables;
- timeout/network failures.

Avoid scanning huge log ranges without filtering.

Use timestamps, error level, path, status code, or relevant keywords where possible.

### 4. Check configuration

Inspect Render configuration relevant to the failing feature.

Check, when applicable:

- runtime version;
- build command;
- start command;
- service root directory;
- branch used for deployment;
- auto-deploy configuration;
- persistent disk mount path;
- environment-variable names;
- environment groups;
- project/environment association;
- custom domain configuration.

Compare production configuration with what the application expects.

Do not print or expose secret values.

For secret environment variables, inspect only safe properties when possible:

- whether the variable exists;
- whether the expected variable name is present;
- whether configuration is attached to the correct service/environment.

If debugging requires inspecting a secret's actual value, request explicit user approval before exposing or changing it, and avoid printing it into the conversation.

### 5. Persistent storage checks

TutorIlya depends on persistent storage for SQLite and uploaded files.

When investigating missing data, disappearing files, or database resets, verify:

- that a persistent disk is attached;
- its mount path;
- that the application database path is located under the persistent mount;
- that uploaded files are located under the persistent mount;
- that the currently running service is using the expected paths.

Compare deployment configuration with application path construction.

A successful deploy does not prove persistent data is configured correctly.

### 6. Environment-variable incidents

Environment variables have previously caused a production AI outage.

When diagnosing API authentication or malformed-header errors:

- verify that the expected variable exists;
- consider whitespace or newline corruption;
- distinguish configuration problems from OpenAI/API/network problems;
- remember that a saved environment-variable change may require a new deployment before the running instance sees it.

Never output complete API keys, passwords, or Authorization headers.

### 7. External API diagnosis

If an external API such as OpenAI is failing, isolate layers.

Check:

1. whether the application reached the external-call code;
2. the application/runtime error;
3. whether credentials appear configured;
4. basic outbound connectivity where appropriate;
5. the exact client library behavior used by the application;
6. provider response when a request actually reaches the provider.

Do not assume billing, networking, credentials, or model availability is the cause without evidence.

### 8. Compare production with local state

When behavior differs between local and Render:

Compare:

- Python version;
- dependency versions;
- environment-variable presence;
- filesystem paths;
- deployed commit;
- database location;
- persistent disk;
- startup command;
- external-service configuration.

Explicitly identify differences instead of immediately modifying application code.

### 9. Production-change policy

Read-only production investigation may proceed automatically when tools are available.

Do not perform production mutations without explicit user approval when they involve:

- changing environment variables;
- modifying secrets;
- changing persistent-disk configuration;
- changing service settings;
- changing build/start commands;
- deleting resources;
- changing databases;
- changing domains;
- rolling back;
- triggering a potentially disruptive redeploy.

Present:

- evidence;
- root-cause hypothesis;
- proposed action;
- expected impact;
- rollback approach.

Then wait for approval.

A normal read-only log or configuration inspection does not require approval.

### 10. Redeploys and restarts

Do not use redeployment as a debugging experiment without a reason.

Before proposing a redeploy, explain what hypothesis it tests.

After a configuration change or redeploy:

- verify deploy success;
- inspect startup logs;
- verify the expected commit/configuration is active;
- reproduce the original failing action;
- confirm the symptom is actually resolved.

### 11. Final production incident report

At the end of the investigation, summarize:

**Symptom**
What users or the system experienced.

**Timeline**
Relevant deploy/configuration/error timestamps.

**Evidence**
Important logs and configuration observations.

**Hypotheses tested**
What was considered and how it was ruled in or out.

**Root cause**
The smallest supported explanation.

**Fix**
What changed.

**Verification**
How the original failure was reproduced and confirmed fixed.

**Prevention**
Tests, validation, monitoring, documentation, or configuration safeguards that should prevent recurrence.