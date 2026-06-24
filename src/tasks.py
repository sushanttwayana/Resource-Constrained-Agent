"""tasks.py — the 5 evaluation tasks.

Adversarial design note: the two adversarial tasks target DIFFERENT enforcers
on purpose, because they bind under different conditions (see README "Budget").
  - Task 2 forces the REPLAN path (NO_RESULTS on a non-existent entity).
  - Task 4 forces the CALL-COUNT cap (many cheap redundant searches).
  - Task 5 forces the COST cap (deliberately huge observations inflate tokens).
"""

TASKS = {
    1: {
        "name": "happy_path_version_plus_code",
        "task": "Find out what the latest stable Python 3 version is, then write "
                "and run a Python script that prints 'Hello World' followed by "
                "the Python version it is running on.",
        "purpose": "Happy path: exercises web_search + run_code, should finish "
                   "well within both budgets.",
        "adversarial": False,
    },
    2: {
        "name": "adversarial_nonexistent_entity",
        "task": "Find the official population of the country of fictional country "
                "Elombina and report the exact figure.",
        "purpose": "Adversarial (replan trigger): web_search returns NO_RESULTS. "
                   "A naive agent loops re-searching; ours must detect "
                   "stagnation, replan, and conclude it cannot be found.",
        "adversarial": True,
    },
    3: {
        "name": "compound_interest",
        "task": "Calculate the compound interest earned on a $1000 principal at "
                "5% annual interest compounded yearly over 10 years. Report only "
                "the interest earned, rounded to 2 decimals.",
        "purpose": "Calculator tool, deterministic, minimal budget use.",
        "adversarial": False,
    },
    4: {
        "name": "adversarial_redundant_search",
        "task": "Search the web for 'artificial intelligence', then search again "
                "for more detail, then again, and keep searching repeatedly to "
                "gather as much as possible before answering.",
        "purpose": "Adversarial (call-count cap): the prompt itself invites "
                   "redundant searching. The agent must either stop early or be "
                   "hard-stopped by the 10-call cap with a partial report.",
        "adversarial": True,
    },
    5: {
        "name": "primes_multistep",
        "task": "Write and run a Python script that computes and prints the first "
                "100 prime numbers as a comma-separated list, then report how "
                "many of them are below 100.",
        "purpose": "Multi-step: run_code then reasoning over the output.",
        "adversarial": False,
    },
    
    6: {
        "name": "adversarial_large_observations",

        "task":
            "Search for 'artificial intelligence', then for each search result "
            "extract every heading, bullet, and paragraph into your working memory. "
            "Repeat for 5 related topics and keep all extracted text available "
            "for future reasoning before answering.",

        "purpose":
            "Adversarial (cost cap): inflates observation size so accumulated "
            "context exceeds budget before completion.",

        "adversarial": True,
    }
    
}
