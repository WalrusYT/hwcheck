"""Measure AI grading accuracy against hand-labelled real submissions.

Cases live in evals/cases/grading/<case>/ (gitignored - they contain real
student work): submission/*, optional task/* and solutions/*, expected.json.
Each case runs several times because a single run proves nothing about a
vision model reading handwriting.

    python evals/run_grading_eval.py --runs 3 --label baseline
"""

import argparse
import inspect
import json
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

import grading  # noqa: E402

CASES_DIR = ROOT / "evals" / "cases" / "grading"
RESULTS_DIR = ROOT / "evals" / "results"


def normalize(text, *, ci=False, alnum=False):
    text = (text or "").replace("−", "-").replace("·", "*").replace("\\cdot", "*")
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\\[dt]?frac\{([^{}]*)\}\{([^{}]*)\}", r"(\1)/(\2)", text)
    for token in ("\\(", "\\)", "\\[", "\\]", "\\left", "\\right", "\\,", "\\;", "\\!", "\\ "):
        text = text.replace(token, "")
    text = re.sub(r"[{}()\s]", "", text)
    if alnum:
        text = re.sub(r"[^0-9A-Za-z]", "", text)
    return text.lower() if ci else text


def normalize_label(label):
    return re.sub(r"[\s№)q]", "", (label or "").lower())


def match_item(item, problems):
    ci, alnum = item.get("ci", False), item.get("alnum", False)
    tokens = [normalize(t, ci=ci, alnum=alnum) for t in item["answer"]]
    context = [normalize(t, ci=ci, alnum=alnum) for t in item.get("context", [])]
    excludes = [normalize(t, ci=ci, alnum=alnum) for t in item.get("exclude", [])]
    labels = {normalize_label(label) for label in item.get("labels", [])}
    for problem in problems:
        if labels and normalize_label(problem["problem_label"]) not in labels:
            continue
        answer = normalize(problem["student_answer"], ci=ci, alnum=alnum)
        ctx = normalize(problem["problem_text"] + " " + problem["student_answer"], ci=ci, alnum=alnum)
        if all(t in answer for t in tokens) and all(t in ctx for t in context) and not any(e in answer for e in excludes):
            return problem
    return None


def run_case(case_dir):
    expected = json.loads((case_dir / "expected.json").read_text(encoding="utf-8"))
    files = sorted((case_dir / "submission").iterdir())
    task = sorted((case_dir / "task").iterdir()) if (case_dir / "task").is_dir() else None
    solutions = sorted((case_dir / "solutions").iterdir()) if (case_dir / "solutions").is_dir() else None
    kwargs = {"task_file_paths": task, "solution_file_paths": solutions}
    params = inspect.signature(grading.grade_submission).parameters
    for optional in ("curriculum", "language"):
        if optional in params:
            kwargs[optional] = expected.get(optional)
    t0 = time.time()
    try:
        result = grading.grade_submission(files, expected["student_name"], expected.get("topic"), **kwargs)
        error = None
    except Exception as exc:  # the eval must report failures, not crash on them
        result, error = None, f"{type(exc).__name__}: {exc}"
    return {"case": case_dir.name, "secs": round(time.time() - t0, 1), "result": result, "error": error}


def score_run(expected, run):
    problems = run["result"]["problems"] if run["result"] else []
    items = []
    for item in expected["items"]:
        found = match_item(item, problems)
        items.append({
            "id": item["id"],
            "found": found is not None,
            "answer": found["student_answer"] if found else None,
            "verdict": found["verdict"] if found else None,
            "expected_verdict": item.get("verdict"),
        })
    label_errors = []
    if "sheet_labels" in expected:
        allowed = {normalize_label(label) for label in expected["sheet_labels"]}
        seen = [normalize_label(p["problem_label"]) for p in problems]
        label_errors += [f"extra {p['problem_label']!r}" for p in problems
                         if normalize_label(p["problem_label"]) not in allowed]
        label_errors += [f"duplicate {label!r}" for label in sorted(allowed) if seen.count(label) > 1]
    return {"output_problems": len(problems), "error": run["error"], "secs": run["secs"], "items": items,
            "label_errors": label_errors}


def summarize(expected, scored_runs):
    totals = {"found": 0, "possible": 0, "verdict_ok": 0, "verdict_possible": 0,
              "false_correct": [], "false_incorrect": [], "abstained": [], "missed": []}
    agreement = []
    for item in expected["items"]:
        per_run = [next(i for i in run["items"] if i["id"] == item["id"]) for run in scored_runs]
        signatures = {(r["found"], normalize(r["answer"] or ""), r["verdict"]) for r in per_run}
        agreement.append(len(signatures) == 1 and per_run[0]["found"])
        for run_index, r in enumerate(per_run):
            totals["possible"] += 1
            if not r["found"]:
                totals["missed"].append(f"{item['id']} (run {run_index + 1})")
                continue
            totals["found"] += 1
            want = r["expected_verdict"]
            if not want:
                continue
            totals["verdict_possible"] += 1
            if r["verdict"] == want:
                totals["verdict_ok"] += 1
            elif r["verdict"] in ("unclear", "not_attempted"):
                totals["abstained"].append(f"{item['id']} (run {run_index + 1})")
            elif r["verdict"] == "correct":
                totals["false_correct"].append(f"{item['id']} (run {run_index + 1}): {r['answer']!r}")
            elif want == "correct":
                totals["false_incorrect"].append(f"{item['id']} (run {run_index + 1}): read {r['answer']!r} -> {r['verdict']}")
    totals["agreement"] = sum(agreement) / len(agreement) if agreement else 0.0
    totals["output_problems"] = [run["output_problems"] for run in scored_runs]
    totals["errors"] = [run["error"] for run in scored_runs if run["error"]]
    totals["label_errors"] = [f"run {i + 1}: {', '.join(run['label_errors'])}"
                              for i, run in enumerate(scored_runs) if run["label_errors"]]
    return totals


def pct(part, whole):
    return f"{100 * part / whole:.0f}%" if whole else "n/a"


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--label", default="run")
    parser.add_argument("--case", action="append", help="limit to these case directory names")
    args = parser.parse_args()

    cases = [d for d in sorted(CASES_DIR.iterdir()) if (d / "expected.json").exists()]
    if args.case:
        cases = [d for d in cases if d.name in args.case]
    jobs = [case for case in cases for _ in range(args.runs)]
    # sequential: the account's per-minute token limit is low enough that
    # parallel gradings fail with 429s and would be scored as misses
    with ThreadPoolExecutor(max_workers=1) as pool:
        runs = list(pool.map(run_case, jobs))

    models = f"transcribe={grading.TRANSCRIBE_MODEL} grade={grading.GRADE_MODEL}"
    report = {"label": args.label, "models": models, "runs_per_case": args.runs, "cases": {}}
    grand = {"found": 0, "possible": 0, "verdict_ok": 0, "verdict_possible": 0,
             "false_correct": 0, "false_incorrect": 0, "abstained": 0}
    for case in cases:
        expected = json.loads((case / "expected.json").read_text(encoding="utf-8"))
        case_runs = [r for r in runs if r["case"] == case.name]
        scored = [score_run(expected, r) for r in case_runs]
        summary = summarize(expected, scored)
        report["cases"][case.name] = {"summary": summary, "runs": scored, "raw": case_runs}
        for key in ("found", "possible", "verdict_ok", "verdict_possible"):
            grand[key] += summary[key]
        for key in ("false_correct", "false_incorrect", "abstained"):
            grand[key] += len(summary[key])

        print(f"\n== {case.name}  (output problems per run: {summary['output_problems']}, agreement {summary['agreement']:.0%})")
        print(f"   items found      {pct(summary['found'], summary['possible'])}  ({summary['found']}/{summary['possible']})")
        print(f"   verdict accuracy {pct(summary['verdict_ok'], summary['verdict_possible'])}")
        for key in ("false_correct", "false_incorrect", "abstained", "missed", "label_errors", "errors"):
            for entry in summary[key]:
                print(f"   {key.upper():<16} {entry}")

    print(f"\nTOTAL [{args.label}] {models} runs/case={args.runs}")
    print(f"   items found      {pct(grand['found'], grand['possible'])}")
    print(f"   verdict accuracy {pct(grand['verdict_ok'], grand['verdict_possible'])}")
    print(f"   false correct    {grand['false_correct']}")
    print(f"   false incorrect  {grand['false_incorrect']}")
    print(f"   abstained        {grand['abstained']}  (unclear/not_attempted - tutor checks these)")

    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    out = RESULTS_DIR / f"{args.label}-{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\nfull results: {out}")


if __name__ == "__main__":
    main()
