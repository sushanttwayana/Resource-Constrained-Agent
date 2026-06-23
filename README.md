# Resource-Constrained Agentic Planning Loop

A ReAct agent that solves tasks under **hard budget limits** — 10 LLM calls and
$0.20 of (mock) cost per task — with real mid-task enforcement, reflection, and
replanning. Built on Groq's free `openai/gpt-oss-120b`.

## Quickstart (single command)

```bash
cp .env.example .env          # then put your free Groq key in .env
docker build -t agent-loop .
docker run --rm --env-file .env agent-loop            # runs all 5 tasks
docker run --rm --env-file .env agent-loop "What is 2^10?"   # one task
docker run --rm --env-file .env agent-loop --task 2    # one built-in task
```

Without Docker:

```bash
pip install -r requirements.txt
export GROQ_API_KEY=...        # or use a .env loader of your choice
python main.py --suite
```

Get a free Groq key (no credit card) at https://console.groq.com.

### Injecting API keys into the container

Keys are read from the environment, never baked into the image. Pass them with
`--env-file .env` (recommended) or `-e GROQ_API_KEY=...`. Only `GROQ_API_KEY`
is required. `TAVILY_API_KEY` is optional (see Tools). `GROQ_MODEL` optionally
overrides the model.

---

## Architecture Overview

A single `AgentState` Pydantic object flows through a ReAct loop. Each turn the
LLM emits one JSON decision (a thought, one tool call *or* a final answer, and a
self-assessment of progress). A budget enforcer wraps the only LLM call site and
raises immediately when either cap is hit, so the loop stops mid-task and the
top-level runner prints a partial-completion report. Three tools — web search,
a sandboxed code executor, and an AST calculator — each run under their own
timeout. A deterministic stagnation detector triggers replanning at zero LLM
cost. All events are written to a self-contained JSON trace.

```
Budget enforcer (hard stop: <10 calls AND <$0.20)  ── wraps every LLM call
        │
   Task ▼
        ReAct loop:  Think ─► Act (1 tool) ─► Observe ─► Reflect/Replan ─┐
        ▲────────────────────────────────────────────────────────────────┘
        │
   Tools: web_search(10s) · run_code(15s) · calculator(5s)
        │
   Result / graceful-exit report  (final answer OR partial state)
```

## Planning Loop

I chose **ReAct** because the assignment is fundamentally about *atomic resource
accounting*, and ReAct's Think→Act→Observe cycle gives a clean unit to charge:
one Think step is exactly one LLM call, so the budget enforcer maps 1:1 onto the
loop without estimating or batching. It is also transparent — the scratchpad is
human-readable, which matters for the graceful-exit report. **Its biggest
weakness is thought spirals**: the model can keep re-reasoning the same sub-step
without taking a useful action, silently burning budget. I mitigate this two
ways — the deterministic stagnation detector (which does not rely on the model
noticing) and the per-turn budget figure injected into the prompt — but the
weakness is intrinsic to ReAct and cannot be fully removed at the loop level.

## Schema Design

All state is typed Pydantic (`src/schema.py`) and everything passes through one
`AgentState`:

- `AgentState` → `task`, `scratchpad: list[Step]`, `budget: BudgetTracker`,
  `final_answer`, `status`, `replan_count`, `error`.
- `Step` → `thought`, `action: ToolCall | None`, `observation: str | None`,
  `progress: ProgressCheck`, `replanned: bool`.
- `BudgetTracker` → call/cost counters, limits, `record_call()`, `is_exhausted()`.

Two deliberate choices: (1) the LLM **never sees raw tool output** — it sees
`render_scratchpad()`, which truncates large observations so a single huge result
can't blow context or token cost; (2) progress is part of `Step`, not a separate
object, so reflection costs no extra LLM call. Typed state also means the trace
and the exit report are just serialisations of the same object.

## Prompt Strategy

The system prompt (`src/prompts.py`) enforces three behaviours: **tool use** is
forced by requiring a strict JSON object with exactly one of `action` /
`final_answer` (combined with Groq's `response_format=json_object`), so the model
cannot answer in prose without acting; **progress checking** is required as a
mandatory `progress` field every turn; **budget awareness** is injected each turn
as a live "BUDGET REMAINING: N calls, $X" line plus an instruction to prefer the
cheapest tool and to stop when a task is impossible. On a replan, a `*** REPLAN
REQUIRED ***` block is injected naming the failure and forbidding repetition.

## Failure Modes

Observed during testing: on the non-existent-entity task (Task 2), the model's
*own* progress self-assessment was unreliable — it sometimes reported
`on_track: true` while re-issuing a doomed search, because it "felt" productive.
The model-based reflection alone would have looped. The **deterministic**
stagnation detector is what actually broke the loop (identical-action and
repeated-NO_RESULTS rules), which is exactly why I did not rely on LLM
self-reflection alone. A second mode: malformed JSON from the model is caught in
`call_llm` and converted into an off-track step rather than crashing the run.

## Future Work

The code executor runs untrusted code in a subprocess on the host with a
timeout, but **not** in a real sandbox — a malicious snippet could still touch
the filesystem or network. With more time I would isolate it (a locked-down
container with no network, read-only FS, resource limits, or a microVM like
Firecracker/gVisor) before trusting it with arbitrary generated code.

## Observability

Tracing is self-contained (a JSON event log per run, `--trace` writes to
`traces/`) so the project runs and is inspectable with zero external accounts.
LangSmith was intentionally **not** adopted: it would add a second required key
and an external dependency to a project graded on single-command reproducibility.
Wrapping `run_agent`/`call_llm` with `@traceable` is a one-line addition if a
hosted UI is later desired.
