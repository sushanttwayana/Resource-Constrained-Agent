"""
tools.py — exactly three tools, each with a real timeout and explicit
exception handling. No bare `except: pass` anywhere.

  1. web_search   — keyless DuckDuckGo by default; Tavily if TAVILY_API_KEY set
  2. run_code     — sandboxed subprocess, never exec()/eval()
  3. calculator   — AST-based safe arithmetic (custom tool)
"""
from __future__ import annotations

import ast
import operator
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dotenv import load_dotenv

import requests

load_dotenv()

WEB_TIMEOUT = 10
CODE_TIMEOUT = 15
CALC_TIMEOUT = 5

_EXECUTOR = ThreadPoolExecutor(max_workers=4)


def _with_timeout(fn, timeout: int, *args, **kwargs) -> str:
    """Run a blocking callable under a wall-clock timeout. Used for the web
    and calculator tools, which are synchronous. (The code tool uses
    subprocess's own timeout, which can actually kill the child process.)"""
    future = _EXECUTOR.submit(fn, *args, **kwargs)
    try:
        return future.result(timeout=timeout)
    except FutureTimeout:
        future.cancel()
        return f"[tool error] operation exceeded {timeout}s timeout"


# --- Tool 1: web search -----------------------------------------------------
def _tavily_search(query: str, max_results: int = 5) -> str:
    key = os.environ["TAVILY_API_KEY"]
    resp = requests.post(
        "https://api.tavily.com/search",
        json={"api_key": key, "query": query, "max_results": max_results},
        timeout=WEB_TIMEOUT,
    )
    resp.raise_for_status()
    data = resp.json()
    results = data.get("results", [])
    if not results:
        return "NO_RESULTS: the web search returned nothing for this query."
    return "\n".join(
        f"- {r.get('title', '')}: {r.get('content', '')[:300]}" for r in results
    )


def _ddg_search(query: str, max_results: int = 5) -> str:
    # `ddgs` is the maintained successor to `duckduckgo_search`.
    from ddgs import DDGS

    with DDGS() as ddgs:
        hits = list(ddgs.text(query, max_results=max_results))
    if not hits:
        return "NO_RESULTS: the web search returned nothing for this query."
    return "\n".join(
        f"- {h.get('title', '')}: {h.get('body', '')[:300]}" for h in hits
    )


def web_search(query: str, max_results: int = 5) -> str:
    """Search the web. Returns a 'NO_RESULTS' sentinel when the query yields
    nothing — the agent uses that signal to replan instead of retrying."""

    def _run() -> str:
        try:
            if os.environ.get("TAVILY_API_KEY"):
                return _tavily_search(query, max_results)
            return _ddg_search(query, max_results)
        except ImportError:
            return "[tool error] web search backend not installed (pip install ddgs)"
        except requests.RequestException as e:
            return f"[tool error] web request failed: {e}"
        except Exception as e:  # explicit, surfaced — not swallowed
            return f"[tool error] web search failed: {type(e).__name__}: {e}"

    return _with_timeout(_run, WEB_TIMEOUT)


# --- Tool 2: code executor --------------------------------------------------
def run_code(code: str) -> str:
    """Execute a Python snippet in an isolated subprocess and return its
    stdout/stderr. Uses subprocess.run with a hard timeout that kills the
    child. Never uses exec()/eval() in-process."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", delete=False
        ) as f:
            f.write(code)
            tmp_path = f.name

        proc = subprocess.run(
            [sys.executable, tmp_path],
            capture_output=True,
            text=True,
            timeout=CODE_TIMEOUT,
            check=False,
        )
        out = (proc.stdout or "").strip()
        err = (proc.stderr or "").strip()
        if proc.returncode != 0:
            return f"[exit {proc.returncode}]\nSTDOUT:\n{out}\nSTDERR:\n{err}"
        return out if out else "[no stdout produced]"
    except subprocess.TimeoutExpired:
        return f"[tool error] code execution exceeded {CODE_TIMEOUT}s timeout"
    except OSError as e:
        return f"[tool error] could not run code: {e}"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try:
                os.unlink(tmp_path)
            except OSError:
                pass  # explicit: cleanup failure is non-fatal and logged nowhere critical


# --- Tool 3: calculator (custom) --------------------------------------------
_ALLOWED_BINOPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_ALLOWED_UNARY = {ast.UAdd: operator.pos, ast.USub: operator.neg}
_MAX_POW_EXP = 1000  # guard against memory-bomb exponents like 9**9**9


def _eval_node(node: ast.AST) -> float:
    if isinstance(node, ast.Expression):
        return _eval_node(node.body)
    if isinstance(node, ast.Constant):
        if isinstance(node.value, (int, float)):
            return node.value
        raise ValueError(f"disallowed constant: {node.value!r}")
    if isinstance(node, ast.BinOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_BINOPS:
            raise ValueError(f"disallowed operator: {op_type.__name__}")
        left, right = _eval_node(node.left), _eval_node(node.right)
        if op_type is ast.Pow and abs(right) > _MAX_POW_EXP:
            raise ValueError("exponent too large")
        return _ALLOWED_BINOPS[op_type](left, right)
    if isinstance(node, ast.UnaryOp):
        op_type = type(node.op)
        if op_type not in _ALLOWED_UNARY:
            raise ValueError(f"disallowed unary operator: {op_type.__name__}")
        return _ALLOWED_UNARY[op_type](_eval_node(node.operand))
    raise ValueError(f"disallowed expression node: {type(node).__name__}")


def calculator(expression: str) -> str:
    """Safely evaluate an arithmetic expression via AST parsing. No eval()."""

    def _run() -> str:
        try:
            tree = ast.parse(expression, mode="eval")
            result = _eval_node(tree)
            return str(result)
        except (ValueError, SyntaxError) as e:
            return f"[tool error] invalid expression: {e}"
        except ZeroDivisionError:
            return "[tool error] division by zero"
        except Exception as e:
            return f"[tool error] calculation failed: {type(e).__name__}: {e}"

    return _with_timeout(_run, CALC_TIMEOUT)


# --- registry the agent loop dispatches on ----------------------------------
TOOLS = {
    "web_search": web_search,
    "run_code": run_code,
    "calculator": calculator,
}

TOOL_SPECS = """
- web_search(query: str): search the web. Returns short result snippets, or a
  line beginning "NO_RESULTS" if nothing was found. Do NOT call it again with
  the same query if it returned NO_RESULTS.
- run_code(code: str): run a Python 3 snippet in a sandbox and get its stdout.
  Use print() to surface results.
- calculator(expression: str): evaluate a single arithmetic expression, e.g.
  "1000 * (1.05 ** 10)". Supports + - * / // % ** and parentheses only.
""".strip()
