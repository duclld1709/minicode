from minicode.evals import EvalContext, original_tests_pass, run_pytest


def check(ctx: EvalContext) -> tuple[bool, str]:
    kept, reason = original_tests_pass(ctx)  # the original tests pass on the agent's code
    if not kept:
        return False, reason
    return run_pytest(ctx.workspace)  # ...and so does the agent's own suite
