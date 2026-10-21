---
name: ai-eval
description: Measure whether TutorIlya's AI features (homework grading, hint chat, performance narrative) actually behave correctly on real student work - use after any change to a prompt, schema, model, or image pipeline, before deploying such a change, or when the tutor reports an AI mistake.
---

# AI evaluation

Verify AI behaviour with numbers from repeated runs, not one good-looking reply.
The same page, prompt, and model have produced 4, 5, and 12 "problems" on three
consecutive runs with different misread digits each time - run every case at
least 3 times and look at agreement.

## Hard rules

- **Never commit real student work.** Cases live in gitignored `evals/cases/`;
  results in gitignored `evals/results/`. Never copy them into a tracked path,
  a test fixture, or a commit message.
- Real API calls cost money and the account is limited to ~30k tokens/min on
  gpt-4o. State the number of calls before a big run; the harness runs
  sequentially on purpose (parallel runs hit 429s that score as misses).
- Schema-valid output is not correct output.
- Always compare with a baseline: run the same cases before the change
  (`git stash` or the `main` commit) and after, same `--runs`.
- `pytest` is for code paths with a fake model; `evals/` is for model behaviour.
  A prompt change needs both.

## 1. Grading eval

```
python evals/run_grading_eval.py --runs 3 --label before-<change>
python evals/run_grading_eval.py --runs 3 --label after-<change> [--case <dir>]
```

Stage models come from env: `OPENAI_TRANSCRIBE_MODEL`, `OPENAI_GRADE_MODEL`
(fallback `OPENAI_MODEL`). Set them in the shell to compare models.

### Case format

```
evals/cases/grading/<case-id>/
  submission/*      # the student's pages (jpg/png/heic/pdf)
  task/*            # the assignment sheet, if the real assignment had one
  solutions/*       # answer key, if it had one
  expected.json
```

```json
{
  "student_name": "Student", "topic": "...", "curriculum": "ru", "language": "ru",
  "items": [
    {"id": "63a", "answer": ["x-5", "y-1"], "verdict": "correct"},
    {"id": "63g", "context": ["5p", "10q"], "answer": ["-5"], "verdict": "correct"},
    {"id": "82zh", "answer": ["a^2+b^2", "2a"], "exclude": ["-b^2"]}
  ]
}
```

An item is *found* when some output problem's normalized `student_answer`
contains every `answer` token, its problem text + answer contain every
`context` token, and no `exclude` token appears. Optional: `labels` (restrict
to these problem labels), `ci` (case-insensitive), `alnum` (compare letters and
digits only). Omit `verdict` when the truth is unknown (e.g. no sheet and the
problem can't be inferred). Normalization strips LaTeX `\( \)`, `\frac{a}{b}` ->
`(a)/(b)`, braces, brackets, and spaces.

Build labels from submissions the tutor corrected and published
(`tutor_result`, `feedback_published = 1`) - and look at the photo yourself
before trusting any label. Verify algebraic verdicts with `math_check`/sympy.

### Metrics

| Metric | Meaning |
|---|---|
| items found | the student's answer was read correctly (transcription) |
| verdict accuracy | verdict equals the expected verdict |
| **false correct** | said correct, truth is not - worst: a wrong answer is praised |
| **false incorrect** | said incorrect/partial, truth is correct - a right answer is penalized |
| abstained | `unclear`/`not_attempted` - safe, the tutor checks it, but costs tutor time |
| agreement | items with identical reading+verdict across runs |

Goal order: 0 false correct, then 0 false incorrect, then fewer abstentions.

### Baseline (2026-09-26, 2 real no-sheet cases x 3 runs)

| pipeline | found | false correct | false incorrect |
|---|---|---|---|
| old single-call gpt-4o | 7% | invented problems | - |
| two-stage gpt-4o | ~40% | 0 | 0 (mostly abstained) |
| two-stage gpt-5.5 | 78% | 0 | 0 after the no-sheet rule (7 before) |

2026-09-28, 4 real cases (2 with a sheet) x 2 runs, after part-by-part
reconciliation and multi-part grading:

| models (transcribe / grade) | uni topology (sheet) | PT dízimas (sheet) | no-sheet cases | false correct / incorrect |
|---|---|---|---|---|
| live code, gpt-4o / gpt-4o | 0% verdicts (all unclear) | 78% | ~40% found | 0 / 1 |
| gpt-4o / gpt-4o | 54% | - | - | 1 / 0 |
| **gpt-4o / gpt-5.5** | **85-90%** | **100%** | 50% / 35% found | **0 / 0** |
| gpt-5.5 / gpt-5.5 | 65% (readings disagree more) | - | 78% found (09-26) | 0 / 0 |

gpt-4o's own answer key was wrong on university analysis (sup/max of
(-1)^n/n, max of 1/n+1/m, min/max of [2,3]∩Q); gpt-5.5 got every part right.
Multi-part answers must be transcribed in full ("inf = ..; sup = ..") - the
last line alone made both readings and the verdicts meaningless.

2026-10-04, `pt_equacoes_unnumbered` (4 pages, sheet whose first 7 equations have
no numbers): live code 5 of 13 with every unnumbered problem graded as the last
one; after unique labels + checker fixes 12 of 13 in every run on gpt-4o and
gpt-5.5 (the 13th is genuinely wrong). Known gpt-4o grading slip that remains:
`pt_dizimas` #10, a correct ordering chain marked incorrect (gpt-5.5: correct).

2026-10-19/20, 10 cases (4 new with sheets: series, logs on dark photos, two
PT sheets; a mock test with sheet + tutor key). **Reading is the main error
source**: gpt-4o reads faint/dark photos as the *right* answers (5^5 for a
written 5, 7 for -11) - 8-10 false "correct" per run on the new cases, which no
grader can undo. gpt-6.1-sol reads verbatim and flags what it can't read
(two readings disagree); gpt-6-astra reads as well at ~3x the price; gpt-5.5
reads well but 3 of its 4 slips moved toward the right answer; gpt-6-luna
can't read. Graders on one shared reading: gpt-5.5 best explanations,
gpt-6.1-sol / astra as thorough but stricter on unevaluated powers and
intermediate steps (partially_correct where the tutor may say correct), gpt-4o
misses sheet requirements and ignores the student's language. After the
math_check fix (sheet-given values, ln identities) and with the tutor key in
the prompt: gpt-6.1-sol 0 false correct on every completed case; mock test
16/18 (II.2 unclear: two readings ordered the same parts differently). Cost per
homework: 4o ~$0.13, 6.1-sol ~$0.20, 5.5 ~$0.70, astra ~$0.90. Eval runs
drained the shared OpenAI balance once - check it before a big run.

With no task sheet the problem is only inferred from the student's work, so
the no-sheet rule turns non-correct verdicts into `unclear`. Cases with the
real sheet attached are the biggest missing piece of this eval set - add them.

## 2. Hint chat eval

```
python evals/run_chat_eval.py --runs 2 [--profile pt-ru] [--sheet path.pdf --forbid "x=3"]
```

Runs profiles (pt-ru, pt-en, ru-ru) x prompts (theory, task help, two injection
probes through `task_number`) and flags: not in the student's language, «вы»,
filler, > 110 words, Portuguese terms written in Cyrillic, asking to "check the
number" with no sheet, and any `--forbid` answer appearing. Also **read the
replies**: the checks don't judge whether the maths is right or the hint helps
(gpt-4o has described critério LAL wrongly).

Prompt lesson: don't put a wrong example in a prompt ("not X") - the model
copies X. Show the right form instead.

Also covered by pytest: a failed model call refunds the coin; `task_number` is
truncated to 20 chars.

## 3. Performance narrative

- every grade it mentions exists in the student's published history;
- it names homework not handed in when there is some, and never when all was
  handed in; with nothing graded it names no strength (gpt-4o invented
  "curiosity" and "determination" until the prompt forbade it); homework titles
  stay as given - Portuguese ones in Latin letters, not "Потенции";
- written in the student's saved language;
- regenerated after a published grade changes; on failure the old one stays.

## 4. Report

- what ran: cases, runs, models, commit;
- before vs after table;
- every false correct / false incorrect / answer leak, individually;
- verdict: `improved`, `no change`, or `regressed` - never "works" without numbers;
- what wasn't evaluated and why.
