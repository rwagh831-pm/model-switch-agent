"""Command line for the Model Switch Agent.

    python run.py lock
    python run.py compare --current claude:claude-haiku-5-5 --candidate claude:claude-sonnet-5-5
    python run.py assess --url https://example.com/release-notes
    python run.py decide --url https://example.com/release-notes --current ... --candidate ...
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv

from msa import lock, runner, verdict

ROOT = Path(__file__).resolve().parent
RESULTS = ROOT / "results"
TASK = ("Fill job application form fields and write short answers using only an applicant's "
        "profile. Priorities: no invented facts, correct structured answers, low cost per call.")


def print_sheet(sheet: dict) -> None:
    cost = "unknown" if sheet["cost_usd"] is None else f"${sheet['cost_usd']:.4f} per run"
    print(f"  {sheet['model']}: worst run {sheet['correct']}/{sheet['cases']} correct "
          f"(each run: {sheet['correct_each_run']}), {sheet['invented_facts']} invented facts, "
          f"{sheet['errors']} failed calls, {cost}, median {sheet['median_seconds']}s per call")


def run_one(model: str, testset: dict, profile: str, repeats: int) -> dict:
    print(f"Testing {model}: {repeats} runs of {len(testset['cases'])} cases", end="", flush=True)
    sheet = runner.run_repeated(model, testset, profile, repeats, on_case=lambda row: print(".", end="", flush=True))
    print()
    return sheet


def write_report(name: str, data: dict) -> Path:
    RESULTS.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    (RESULTS / f"{stamp}-{name}.json").write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [f"# {name}", "", f"Run: {data['ran_at']}"]
    if data.get("assessment"):
        a = data["assessment"]
        lines += ["", f"**Agent's assessment:** {a['decision']}. {a['reason']}"]
        lines += [f'- "{quote}"' for quote in a["evidence"]]
    if data.get("result"):
        lines += ["", f"**Verdict: {data['result']['verdict']}.** {data['result']['reason']}", "",
                  "| Model | Worst run correct | Each run | Failed calls | Invented facts | Cost per run (USD) | Median seconds |",
                  "|---|---|---|---|---|---|---|"]
        for sheet in (data["current"], data["candidate"]):
            lines.append(f"| {sheet['model']} | {sheet['correct']}/{sheet['cases']} | {sheet['correct_each_run']} | "
                         f"{sheet['errors']} | {sheet['invented_facts']} | {sheet['cost_usd']} | {sheet['median_seconds']} |")
        lines += ["", "## Answers marked wrong in the worst run", ""]
        for sheet in (data["current"], data["candidate"]):
            misses = [r for r in sheet["rows"] if not r["correct"]]
            lines.append(f"**{sheet['model']}:** {len(misses)}")
            lines += [f"- {r['id']}: {r['why']}" for r in misses]
    path = RESULTS / f"{stamp}-{name}.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def compare(current: str, candidate: str, repeats: int) -> dict:
    locked = lock.verify_lock()
    rules = json.loads((ROOT / "decision_rules.json").read_text(encoding="utf-8"))
    testset, profile = runner.load_testset()
    now, new = run_one(current, testset, profile, repeats), run_one(candidate, testset, profile, repeats)
    return {"ran_at": datetime.now().isoformat(timespec="seconds"), "locked_at_utc": locked["locked_at_utc"],
            "current": now, "candidate": new, "result": verdict.decide(now, new, rules)}


def assess(url: str) -> dict:
    from msa.agent import assess_release  # Imported here so offline commands don't need the SDK.

    return asyncio.run(assess_release(url, TASK))


def main() -> int:
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("lock", help="lock the rules and test set before any run")
    for name in ("compare", "decide"):
        p = sub.add_parser(name)
        p.add_argument("--current", required=True)
        p.add_argument("--candidate", required=True)
        p.add_argument("--repeats", type=int, default=3, help="full test runs per model (default 3)")
        if name == "decide":
            p.add_argument("--url", required=True)
    sub.add_parser("assess").add_argument("--url", required=True)
    args = parser.parse_args()

    try:
        if args.command == "lock":
            print(json.dumps(lock.create_lock(), indent=2))
            print("Locked. Commit results/lock.json to git before running tests.")
            return 0

        data = {"ran_at": datetime.now().isoformat(timespec="seconds")}
        if args.command in ("assess", "decide"):
            data["assessment"] = assess(args.url)
            print(f"Agent: {data['assessment']['decision']}. {data['assessment']['reason']}")
        if args.command == "compare" or (args.command == "decide" and data["assessment"]["decision"] == "test"):
            data.update(compare(args.current, args.candidate, args.repeats))
            print_sheet(data["current"])
            print_sheet(data["candidate"])
            print(f"VERDICT: {data['result']['verdict']}. {data['result']['reason']}")
            print("You make the final decision. Nothing has been changed.")
        elif args.command == "decide":
            print("No test run, because the agent did not recommend one.")

        print(f"Report: {write_report(args.command, data).relative_to(ROOT)}")
        return 0
    except RuntimeError as exc:
        print(f"Stopped: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
