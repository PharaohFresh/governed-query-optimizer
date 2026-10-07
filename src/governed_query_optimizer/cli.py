from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path

from .engine import FIXTURES, ValidationError, approve_plan, evaluate_case, make_plan, stage_plan, summarize_workloads


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def save_new(path, value):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2)
        handle.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description="Verify SQL optimization before local, approval-bound staging.")
    commands = parser.add_subparsers(dest="command", required=True)
    demo = commands.add_parser("demo")
    demo.add_argument("--output", type=Path)
    evaluate = commands.add_parser("evaluate")
    evaluate.add_argument("case_id")
    plan = commands.add_parser("plan")
    plan.add_argument("case_id")
    plan.add_argument("--output", required=True)
    approve = commands.add_parser("approve")
    approve.add_argument("--plan", required=True)
    approve.add_argument("--actor", required=True)
    approve.add_argument("--output", required=True)
    stage = commands.add_parser("stage")
    stage.add_argument("--plan", required=True)
    stage.add_argument("--approval", required=True)
    stage.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "demo":
            cases = load(FIXTURES / "cases.json")
            evaluations = [evaluate_case(case["id"]) for case in cases]
            output = args.output or Path("artifacts") / ("demo-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ"))
            output.mkdir(parents=True, exist_ok=False)
            history = summarize_workloads(load(FIXTURES / "jobs.json"))
            report = {"data_origin": "synthetic", "evaluations": evaluations, "workload_intake": history}
            save_new(output / "report.json", report)
            for case, evaluation in zip(cases, evaluations):
                result = "ELIGIBLE" if evaluation["eligible"] else "BLOCKED"
                print(f"[{result}] {case['id']}: {evaluation['reason']}")
                if evaluation["eligible"] != case["expected_eligible"]:
                    raise ValidationError("Demo verdict regressed: " + case["id"])
            save_new(output / "safe_plan.json", make_plan("preaggregate"))
            print("[OK] All expected verdicts reproduced; no query was staged or deployed.")
            print("Artifacts: " + str(output))
        elif args.command == "evaluate":
            result = evaluate_case(args.case_id)
            print(json.dumps(result, indent=2))
            return 0 if result["eligible"] else 1
        elif args.command == "plan":
            save_new(args.output, make_plan(args.case_id))
            print("[OK] Exact candidate plan written; approval is still required.")
        elif args.command == "approve":
            save_new(args.output, approve_plan(load(args.plan), args.actor))
            print("[OK] Local approval attestation written for this exact plan.")
        else:
            print(json.dumps(stage_plan(load(args.plan), load(args.approval), args.output), indent=2))
    except (ValidationError, OSError, KeyError, ValueError) as exc:
        print("[BLOCKED] " + str(exc))
        return 1
    return 0
