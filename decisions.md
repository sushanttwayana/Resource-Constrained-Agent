# Engineering Decisions : As per asked in the task to follow the pattern. 

**1. Model**
I considered `Groq-hosted models` because they are open-source, readily accessible, and can be used free of charge by obtaining an API key from the Groq Console. I chose `llama-3.3-70b-versatile` because it was stable, available, and performed reliably during development. The model offered strong reasoning and instruction-following capabilities while maintaining fast response times through Groq's inference infrastructure, making it well-suited for the project's agentic workflow. The model selection is controlled through a single environment-variable configuration `(GROQ_MODEL)` so that future model migrations can be performed without modifying the application code.

**2. Reflection mechanism**
I considered making reflection a separate LLM call (a dedicated "progress
evaluator" prompt) but chose to fold the progress self-assessment into the same
JSON output as the Think step **and** add a deterministic stagnation detector,
because under a 10-call budget a separate reflection call would consume one of
every two calls — halving the actions the agent can take. The deterministic
detector (repeated action / repeated observation / two consecutive off-track
steps) also makes the replan trace reproducible rather than dependent on the
model recognising it is stuck.

**3. Web search backend**
I considered Tavily (purpose-built for agents, cleaner results) but chose keyless
DuckDuckGo (`ddgs`) as the default because the project is graded on single-command
reproducibility, and Tavily-as-default would force the reviewer to sign up for a
second API key just to run the repo. Tavily is supported as an optional upgrade
when `TAVILY_API_KEY` is present.

**4. Calculator implementation**
I considered `eval()` for the calculator but chose an AST-based evaluator with an
operator allowlist (and an exponent-size guard against memory bombs) because
`eval()` is a code-execution vulnerability even inside a container, and the
assignment's prohibition on bare-except handling reflects the same defensive
posture — a tool should fail loudly and safely, not silently.

**5. Tool-use protocol**
I considered Groq's native function-calling API but chose a JSON-protocol ReAct
loop (strict `response_format=json_object`) because owning the protocol makes the
budget accounting and the trace explicit, keeps the loop portable across the
churning Groq model catalog, and makes malformed output recoverable rather than
an opaque SDK error. The trade-off is slightly more parsing code, handled in
`call_llm`.

**6. Observability**
I considered LangSmith (the conventional choice) but chose a self-contained JSON
trace because LangSmith adds a third required API key and an external dependency
to a project whose primary grading criterion is single-command reproducibility,
and a "trace screenshot" deliverable depends on a live account. The trace log
gives the same per-step inputs/outputs/cost offline.
