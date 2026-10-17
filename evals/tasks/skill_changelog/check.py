import re

from minicode.evals import EvalContext, run_pytest

ENTRY = re.compile(r"^- (feat|fix|refactor|docs): \S.*$", re.MULTILINE)


def check(ctx: EvalContext) -> tuple[bool, str]:
    if not any(c.name == "load_skill" for c in ctx.tool_calls):
        return False, "never loaded the changelog-entry skill"
    passed, summary = run_pytest(ctx.workspace)
    if not passed:
        return False, summary
    changelog = (ctx.workspace / "CHANGELOG.md").read_text(encoding="utf-8")
    unreleased = changelog.split("## Unreleased", 1)[-1].split("## 1.0.0", 1)[0]
    if not ENTRY.search(unreleased):
        return False, "no '- <type>: ...' line under ## Unreleased"
    if "- feat: first release" not in changelog.split("## 1.0.0", 1)[-1]:
        return False, "the released section was modified"
    return True, "fixed, and recorded in CHANGELOG.md per the skill"
