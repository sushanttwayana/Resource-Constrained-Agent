# Test Results

> **How to (re)generate this:** run `python main.py --suite --trace`. The
> per-task mechanics below (budget caps, stagnation/replan triggers, tool
> behaviour) were verified offline with a deterministic test harness. The
> end-to-end task narratives depend on the live model and live web results —
> run the suite with your key and confirm/replace the "Live outcome" lines with
> your actual output before submitting.

## Verified offline (deterministic, no model/network)

- **Calculator** correctly evaluates arithmetic, rejects non-arithmetic input
  (`__import__('os')` → rejected as a disallowed `Call` node), guards against
  memory-bomb exponents (`9 ** 9999` → rejected), and handles division by zero.
- **Code executor** runs snippets, captures stderr on non-zero exit, and a
  `time.sleep(30)` snippet is killed at the 15s timeout.
- **Budget caps fire independently:** ten ~1k-token calls hit the **call-count
  cap** at $0.125 (cost still under $0.20); three ~6k-token calls hit the
  **cost cap** at $0.222 (before the 10-call cap). Both stop via
  `BudgetExhaustedError`, which carries the partial state.
- **Stagnation detector** fires on identical repeated actions, on repeated
  observations, and on two consecutive off-track steps; returns `None` on
  healthy progress.

## Per-task results

### Task 1 — happy path (web + code) — *not adversarial*
Find latest Python version, then run a script printing Hello World + version.
- Expected: 1 web_search, 1 run_code, then final answer. ~3–4 calls, well under
  budget. No replan.
- Live outcome: _<fill in from your run>_

### Task 2 — non-existent entity — **ADVERSARIAL (replan trigger)**
Find the population of fictional "Elbonia".
- Mechanism: web_search returns `NO_RESULTS`. A naive agent re-searches forever.
  Ours detects repeated NO_RESULTS / identical action, injects a REPLAN, and the
  agent concludes the entity does not exist. **This is the required replanning
  trace.** `replan_count >= 1`, status `completed` with an "cannot be found"
  answer, well under budget.
- Live outcome: _<fill in — capture the `>>> REPLAN TRIGGERED` line and the
  trace; this is the single most important trace to show the evaluator>_

### Task 3 — compound interest — *not adversarial*
Interest on $1000 @ 5% compounded yearly for 10 years.
- Expected: 1 calculator call `1000 * (1.05 ** 10) - 1000` → **628.89**. 1–2
  calls. (Verified: `1000 * (1.05 ** 10)` = 1628.8946…, so interest = 628.89.)
- Live outcome: _<fill in from your run>_

### Task 4 — redundant searching — **ADVERSARIAL (call-count cap)**
Prompt instructs the agent to search repeatedly without end.
- Mechanism: if the model obeys the prompt it issues many cheap searches and is
  **hard-stopped at the 10-call cap**, producing a partial-completion report
  listing the steps done before the stop. (If the model is well-behaved it may
  stop early via stagnation/replan instead — both are acceptable; document
  whichever you observe.) Expect status `budget_exhausted` with
  `reason = call-count cap` OR an early `completed`/replan.
- Live outcome: _<fill in — capture the `!!! HARD STOP` line and the partial
  report>_

### Task 5 — first 100 primes (multi-step) — *not adversarial*
Write/run code for first 100 primes, then count how many are < 100.
- Expected: 1 run_code producing the list, then reasoning. There are **25**
  primes below 100, so the final answer should be 25. ~2–4 calls.
- Live outcome: _<fill in from your run>_

## Suite summary table

Paste the auto-printed `SUITE SUMMARY` table here after running
`python main.py --suite`, e.g.:

```
 #  name                             status             calls     cost  replans
 1  happy_path_version_plus_code     completed              4   0.05xx        0
 2  adversarial_nonexistent_entity   completed              3   0.03xx        1
 3  compound_interest                completed              2   0.0xxx        0
 4  adversarial_redundant_search     budget_exhausted      10   0.1xxx        0
 5  primes_multistep                 completed              3   0.0xxx        0
```
