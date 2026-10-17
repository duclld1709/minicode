from minicode.evals import EvalContext, original_tests_pass, run_pytest


def check(ctx: EvalContext) -> tuple[bool, str]:
    kept, reason = original_tests_pass(ctx)
    if not kept:
        return False, reason
    return run_pytest(ctx.workspace)
