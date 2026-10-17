import subprocess
import sys

from minicode.evals import EvalContext, run_pytest

# Hidden acceptance checks: the agent never sees these.
HIDDEN = """
from textutils import is_palindrome
assert is_palindrome("A man, a plan, a canal: Panama")
assert is_palindrome("Racecar")
assert is_palindrome("No 'x' in Nixon")
assert not is_palindrome("hello")
assert not is_palindrome("ab")
"""


def check(ctx: EvalContext) -> tuple[bool, str]:
    tests = (ctx.workspace / "tests" / "test_textutils.py").read_text(encoding="utf-8")
    if "is_palindrome" not in tests:
        return False, "no tests for is_palindrome"
    hidden = subprocess.run(
        [sys.executable, "-c", HIDDEN], cwd=ctx.workspace, capture_output=True, timeout=60
    )
    if hidden.returncode != 0:
        return False, "hidden checks failed: " + hidden.stderr.decode(errors="replace")[-200:]
    return run_pytest(ctx.workspace)
