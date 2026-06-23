"""main.py — single-command entry point.

Usage:
  python main.py "your task here"     # run an arbitrary task
  python main.py --task 3             # run one of the 5 built-in tasks
  python main.py --suite              # run all 5 tasks (default if no args)
  python main.py --suite --trace      # also dump JSON traces to ./traces/
"""
from __future__ import annotations

import argparse
import os
import sys

# allow `python main.py` from repo root without installing as a package
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.agent import report, run_agent, Tracer  # noqa: E402
from src.schema import AgentState, BudgetTracker  # noqa: E402
from tasks import TASKS  # noqa: E402


def run_one(task_text: str, dump_trace: bool = False) -> AgentState:
    state = AgentState(task=task_text, budget=BudgetTracker())
    tracer = Tracer(task_text)
    state, tracer = run_agent(state, tracer=tracer, verbose=True)
    print("\n" + report(state))
    if dump_trace:
        os.makedirs("traces", exist_ok=True)
        fname = "traces/" + "".join(
            c if c.isalnum() else "_" for c in task_text[:40]
        ) + ".json"
        with open(fname, "w") as f:
            f.write(tracer.dump())
        print(f"(trace written to {fname})")
    return state


def run_suite(dump_trace: bool = False):
    summary = []
    for i in sorted(TASKS):
        t = TASKS[i]
        print("\n" + "#" * 64)
        print(f"# TASK {i}: {t['name']}  {'[ADVERSARIAL]' if t['adversarial'] else ''}")
        print(f"# {t['task']}")
        print("#" * 64)
        state = run_one(t["task"], dump_trace=dump_trace)
        summary.append((i, t["name"], state.status, state.budget.llm_calls_used,
                        round(state.budget.cost_used, 4), state.replan_count))

    print("\n" + "=" * 64)
    print("SUITE SUMMARY")
    print("=" * 64)
    print(f"{'#':>2}  {'name':<32} {'status':<18} {'calls':>5} {'cost':>8} {'replans':>8}")
    for i, name, status, calls, cost, replans in summary:
        print(f"{i:>2}  {name:<32} {status:<18} {calls:>5} {cost:>8} {replans:>8}")


def main():
    ap = argparse.ArgumentParser(description="Resource-constrained ReAct agent")
    ap.add_argument("task", nargs="?", help="free-text task to run")
    ap.add_argument("--task", type=int, dest="task_num", help="run built-in task 1-5")
    ap.add_argument("--suite", action="store_true", help="run all 5 built-in tasks")
    ap.add_argument("--trace", action="store_true", help="dump JSON traces")
    args = ap.parse_args()

    if args.task_num:
        run_one(TASKS[args.task_num]["task"], dump_trace=args.trace)
    elif args.task:
        run_one(args.task, dump_trace=args.trace)
    else:
        run_suite(dump_trace=args.trace)  # default: full suite


if __name__ == "__main__":
    main()
