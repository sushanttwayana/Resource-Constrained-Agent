"""llm.py — the ONLY place the model is called, so the ONLY place the budget
can be charged. The enforcer checks before the call (refuse to start) and after
(refuse to continue) — a real hard stop via exception, not a warning."""
from __future__ import annotations

import json
import os

from groq import Groq
from dotenv import load_dotenv
from .schema import AgentState, BudgetExhaustedError

load_dotenv()

### groq models 
# MODEL_ID = os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b")
MODEL_ID = os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile")

_client: Groq | None = None


def _get_client() -> Groq:
    global _client
    if _client is None:
        if not os.environ.get("GROQ_API_KEY"):
            raise RuntimeError(
                "GROQ_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        _client = Groq()
    return _client


def call_llm(state: AgentState, messages: list[dict]) -> dict:
    """Budget-enforced LLM call returning the parsed JSON action dict."""
    # Gate 1: refuse to even start if already exhausted.
    if state.budget.is_exhausted():
        raise BudgetExhaustedError(state)

    client = _get_client()
    resp = client.chat.completions.create(
        model=MODEL_ID,
        messages=messages,
        temperature=0.2,
        max_completion_tokens=800,
        response_format={"type": "json_object"},
    )

    usage = resp.usage
    state.budget.record_call(
        tokens_in=usage.prompt_tokens,
        tokens_out=usage.completion_tokens,
    )

    content = resp.choices[0].message.content or "{}"

    # Gate 2: this call may have pushed us over. Stop before acting on it.
    if state.budget.is_exhausted():
        raise BudgetExhaustedError(state)

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        # Surface a structured error the loop can recover from rather than crash.
        return {
            "thought": "model returned non-JSON; treating as malformed",
            "action": None,
            "final_answer": None,
            "progress": {"on_track": False, "note": "malformed model output"},
            "_parse_error": content[:300],
        }
