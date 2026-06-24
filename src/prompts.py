"""prompts.py — system prompt construction.

The prompt enforces three things the assignment grades on:
  1. tool use (the model must emit a strict JSON action, never prose)
  2. progress checking (every turn carries a self-assessment)
  3. budget awareness (remaining budget is injected each turn)
"""
from __future__ import annotations

from .schema import AgentState
from .tools import TOOL_SPECS

SYSTEM_PROMPT = f"""You are a resource-constrained ReAct agent. You solve a task
by repeatedly reasoning, then either calling ONE tool or giving a final answer.

You have these tools:
{TOOL_SPECS}

HARD RULES:
- You operate under a strict budget. When it runs out you will be stopped
  mid-task, so do not waste calls. Prefer the cheapest tool that works.
- Reason first, then act. Take exactly ONE action per turn.
- If a tool returned NO_RESULTS or an error twice, the approach is failing:
  CHANGE strategy. Do not repeat an identical action.
- When you have enough information, stop and return final_answer. If the task
  is impossible (e.g. asking about something that does not exist), say so in
  final_answer rather than searching forever.

You MUST reply with a single JSON object and nothing else, of this shape:
{{
  "thought": "<your reasoning for this turn>",
  "action": {{"tool": "<tool name>", "args": {{...}}}}   // OR null
  "final_answer": "<answer>"                               // OR null
  "progress": {{"on_track": true/false, "note": "<why>"}}
}}

Exactly one of "action" or "final_answer" must be non-null. "progress" reflects
whether the LAST observation moved you closer to the goal."""


def build_messages(state: AgentState, replan_hint: str | None = None) -> list[dict]:
    remaining_calls = state.budget.llm_calls_limit - state.budget.llm_calls_used
    remaining_cost = state.budget.cost_limit - state.budget.cost_used
    budget_line = (
        f"BUDGET REMAINING: {remaining_calls} LLM calls, "
        f"${remaining_cost:.4f} of mock cost."
    )
    user = f"""TASK: {state.task}

{budget_line}

History so far:
{state.render_scratchpad()}
"""
    if replan_hint:
        user += (
            f"\n*** REPLAN REQUIRED *** Your recent steps have not made progress "
            f"({replan_hint}). Do NOT repeat the same action. Try a different tool "
            f"or conclude the task cannot be completed.\n"
        )
    user += "\nProduce your next JSON object now."
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]
