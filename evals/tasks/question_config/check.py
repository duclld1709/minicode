from minicode.evals import EvalContext, contains_all


def check(ctx: EvalContext) -> tuple[bool, str]:
    if contains_all(ctx.final_text, ["8420", "APP_PORT"]):
        return True, "names port 8420 and APP_PORT"
    return False, "answer is missing 8420 or APP_PORT"
