"""
schema.py — the single source of truth for agent state.

Everything the loop, tools, and LLM exchange flows through these Pydantic
models. The LLM never sees raw tool output; it sees `scratchpad` rendered from
these typed objects. This makes state inspectable, serialisable (for the trace
log and the graceful-exit report), and impossible to silently corrupt.
"""
from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, Field


# --- Mock pricing -----------------------------------------------------------
# We use a FREE model (Groq gpt-oss-120b), so real cost is $0. The assignment
# requires simulating cost, so we assign mock per-token rates. These are tuned
# deliberately: at ~1k-token calls the 10-call cap binds first, but a task that
# stuffs large observations into context will trip the $0.20 cost cap first.
# This is what lets us demonstrate BOTH enforcers independently (see README).
MOCK_PRICE_PER_1K_INPUT = 0.01
MOCK_PRICE_PER_1K_OUTPUT = 0.03


class BudgetTracker(BaseModel):
    """Tracks consumption against two independent hard caps."""

    llm_calls_used: int = 0
    llm_calls_limit: int = 10
    cost_used: float = 0.0
    cost_limit: float = 0.20

    # bookkeeping for the report
    total_tokens_in: int = 0
    total_tokens_out: int = 0

    def record_call(self, tokens_in: int, tokens_out: int) -> None:
        self.llm_calls_used += 1
        self.total_tokens_in += tokens_in
        self.total_tokens_out += tokens_out
        self.cost_used += (
            tokens_in / 1000.0 * MOCK_PRICE_PER_1K_INPUT
            + tokens_out / 1000.0 * MOCK_PRICE_PER_1K_OUTPUT
        )

    def is_exhausted(self) -> bool:
        return (
            self.llm_calls_used >= self.llm_calls_limit
            or self.cost_used >= self.cost_limit
        )

    def reason(self) -> str:
        """Which cap (if any) is responsible for exhaustion."""
        if self.llm_calls_used >= self.llm_calls_limit:
            return f"call-count cap ({self.llm_calls_used}/{self.llm_calls_limit} calls)"
        if self.cost_used >= self.cost_limit:
            return f"cost cap (${self.cost_used:.4f}/${self.cost_limit:.2f})"
        return "not exhausted"


class ToolCall(BaseModel):
    tool: str
    args: dict = Field(default_factory=dict)


class ProgressCheck(BaseModel):
    """The model's own assessment, returned in the SAME call as the thought.

    Folding this into the Think step (rather than a separate LLM call) is a
    deliberate budget decision: a separate reflection call would halve the
    number of actions possible under a 10-call cap. See decisions.md.
    """

    on_track: bool = True
    note: str = ""


class Step(BaseModel):
    step_num: int
    thought: str = ""
    action: Optional[ToolCall] = None
    observation: Optional[str] = None
    progress: ProgressCheck = Field(default_factory=ProgressCheck)
    replanned: bool = False  # set when this step was forced by a replan


class AgentState(BaseModel):
    task: str
    scratchpad: list[Step] = Field(default_factory=list)
    budget: BudgetTracker = Field(default_factory=BudgetTracker)
    final_answer: Optional[str] = None
    status: Literal[
        "running", "completed", "budget_exhausted", "error", "max_steps"
    ] = "running"
    replan_count: int = 0
    error: Optional[str] = None

    def render_scratchpad(self) -> str:
        """Format the history as the LLM sees it. Observations are truncated
        defensively so a single huge tool result cannot blow the context (and
        so we can reason about token cost)."""
        if not self.scratchpad:
            return "(no steps yet)"
        lines = []
        for s in self.scratchpad:
            lines.append(f"--- Step {s.step_num} ---")
            if s.replanned:
                lines.append("[REPLAN was triggered before this step]")
            lines.append(f"Thought: {s.thought}")
            if s.action:
                lines.append(f"Action: {s.action.tool}({s.action.args})")
            if s.observation is not None:
                obs = s.observation
                if len(obs) > 2000:
                    obs = obs[:2000] + f"... [truncated, {len(obs)} chars total]"
                lines.append(f"Observation: {obs}")
            lines.append(
                f"Progress: on_track={s.progress.on_track} ({s.progress.note})"
            )
        return "\n".join(lines)


class BudgetExhaustedError(Exception):
    """Raised the instant a cap is hit. Carries the partial state so the
    top-level runner can produce the graceful-exit report. This is the
    mechanism for a real hard stop — not a printed warning."""

    def __init__(self, state: AgentState):
        self.partial_state = state
        super().__init__(f"Budget exhausted: {state.budget.reason()}")
