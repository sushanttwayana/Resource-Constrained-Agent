"""agent.py — the ReAct planning loop with reflection and replanning.

Reflection is two-layered:
  (a) MODEL self-assessment, returned inside each Think step's JSON (free — no
      extra LLM call), and
  (b) a DETERMINISTIC stagnation detector that catches repeated actions /
      repeated observations / repeated NO_RESULTS at zero cost.

When stagnation is detected, the next turn is forced into a replan with an
explicit corrective hint. (b) guarantees a reproducible replan trace; it does
not depend on the model noticing it is stuck.
"""
from __future__ import annotations

import json
import time

from .llm import MODEL_ID, call_llm
from .prompts import build_messages
from .schema import (
    AgentState,
    BudgetExhaustedError,
    ProgressCheck,
    Step,
    ToolCall,
)
from .tools import TOOLS

MAX_STEPS = 25  # safety net independent of budget (loop can never run forever)


class Tracer:
    """Self-contained structured trace. No external service required."""

    def __init__(self, task: str):
        self.events: list[dict] = []
        self.task = task

    def log(self, event: str, **data):
        self.events.append({"t": round(time.time(), 3), "event": event, **data})

    def dump(self) -> str:
        return json.dumps({"task": self.task, "events": self.events}, indent=2)


def _action_signature(action: ToolCall | None) -> str | None:
    if action is None:
        return None
    return f"{action.tool}:{json.dumps(action.args, sort_keys=True)}"


def _detect_stagnation(state: AgentState) -> str | None:
    """Return a replan hint if the agent is stuck, else None. Pure function of
    state — deterministic and free."""
    steps = state.scratchpad
    if len(steps) < 2:
        return None

    last, prev = steps[-1], steps[-2]

    # 1. Identical action repeated.
    if (
        _action_signature(last.action) is not None
        and _action_signature(last.action) == _action_signature(prev.action)
    ):
        return "the same action was issued twice in a row"

    # 2. Same observation twice (e.g. NO_RESULTS, or identical error).
    if (
        last.observation is not None
        and last.observation == prev.observation
    ):
        return "the last two tool calls returned the same result"

    # 3. Model self-reported off-track twice in a row.
    if not last.progress.on_track and not prev.progress.on_track:
        return "progress has stalled for two consecutive steps"

    return None


def run_agent(state: AgentState, tracer: Tracer | None = None, verbose: bool = True):
    """Run the ReAct loop in place on `state`. Returns (state, tracer)."""
    tracer = tracer or Tracer(state.task)
    tracer.log("start", task=state.task, model=MODEL_ID,
               call_limit=state.budget.llm_calls_limit,
               cost_limit=state.budget.cost_limit)

    pending_replan_hint: str | None = None

    try:
        for step_num in range(1, MAX_STEPS + 1):
            messages = build_messages(state, replan_hint=pending_replan_hint)

            # --- THINK (budget enforced inside) ---
            decision = call_llm(state, messages)

            step = Step(
                step_num=step_num,
                thought=decision.get("thought", ""),
                replanned=pending_replan_hint is not None,
            )
            prog = decision.get("progress") or {}
            step.progress = ProgressCheck(
                on_track=bool(prog.get("on_track", True)),
                note=str(prog.get("note", "")),
            )
            pending_replan_hint = None  # consumed

            tracer.log("think", step=step_num, thought=step.thought[:200],
                       on_track=step.progress.on_track,
                       calls=state.budget.llm_calls_used,
                       cost=round(state.budget.cost_used, 4))

            # --- terminal: final answer ---
            if decision.get("final_answer"):
                step.observation = None
                state.scratchpad.append(step)
                state.final_answer = decision["final_answer"]
                state.status = "completed"
                tracer.log("final_answer", answer=state.final_answer[:300])
                if verbose:
                    _print_step(step)
                break

            # --- ACT ---
            action = decision.get("action")
            if not action or "tool" not in action:
                step.observation = "[loop error] no valid action or final_answer"
                step.progress = ProgressCheck(on_track=False, note="no action emitted")
                state.scratchpad.append(step)
                pending_replan_hint = "the model produced neither an action nor an answer"
                if verbose:
                    _print_step(step)
                continue

            tool_name = action["tool"]
            tool_args = action.get("args", {}) or {}
            step.action = ToolCall(tool=tool_name, args=tool_args)

            if tool_name not in TOOLS:
                observation = f"[tool error] unknown tool '{tool_name}'"
            else:
                tracer.log("act", step=step_num, tool=tool_name, args=tool_args)
                observation = TOOLS[tool_name](**tool_args)

            step.observation = observation
            tracer.log("observe", step=step_num, observation=observation[:300])

            state.scratchpad.append(step)
            if verbose:
                _print_step(step)

            # --- REFLECT / REPLAN (deterministic, free) ---
            hint = _detect_stagnation(state)
            if hint:
                state.replan_count += 1
                pending_replan_hint = hint
                tracer.log("replan", step=step_num, reason=hint,
                           replan_count=state.replan_count)
                if verbose:
                    print(f"    >>> REPLAN TRIGGERED: {hint}")
        else:
            # for-loop exhausted without break
            state.status = "max_steps"
            tracer.log("max_steps_reached", steps=MAX_STEPS)

    except BudgetExhaustedError as e:
        state.status = "budget_exhausted"
        tracer.log("budget_exhausted", reason=state.budget.reason())
        if verbose:
            print(f"\n!!! HARD STOP — budget exhausted: {state.budget.reason()}")
    except Exception as e:  # explicit catch-all that records, never silently passes
        state.status = "error"
        state.error = f"{type(e).__name__}: {e}"
        tracer.log("error", error=state.error)
        if verbose:
            print(f"\n!!! ERROR: {state.error}")

    return state, tracer


def _print_step(step: Step):
    print(f"\n[Step {step.step_num}]{' (post-replan)' if step.replanned else ''}")
    print(f"  Thought: {step.thought}")
    if step.action:
        print(f"  Action:  {step.action.tool}({step.action.args})")
    if step.observation is not None:
        obs = step.observation if len(step.observation) < 300 else step.observation[:300] + "..."
        print(f"  Observe: {obs}")
    print(f"  Progress: on_track={step.progress.on_track} ({step.progress.note})")


def report(state: AgentState) -> str:
    """The graceful-exit / completion report printed at the end of every run."""
    b = state.budget
    lines = [
        "=" * 64,
        f"TASK: {state.task}",
        f"STATUS: {state.status.upper()}",
        f"Steps completed: {len(state.scratchpad)}",
        f"LLM calls used: {b.llm_calls_used}/{b.llm_calls_limit}",
        f"Mock cost used: ${b.cost_used:.4f}/${b.cost_limit:.2f}  "
        f"(tokens in/out: {b.total_tokens_in}/{b.total_tokens_out})",
        f"Replans triggered: {state.replan_count}",
    ]
    if state.status == "budget_exhausted":
        lines.append(f"Stopped by: {b.reason()}")
        lines.append("Partial progress before stop:")
        for s in state.scratchpad:
            act = f"{s.action.tool}" if s.action else "(no action)"
            lines.append(f"  - step {s.step_num}: {act}")
    if state.final_answer:
        lines.append(f"FINAL ANSWER: {state.final_answer}")
    if state.error:
        lines.append(f"ERROR: {state.error}")
    lines.append("=" * 64)
    return "\n".join(lines)
