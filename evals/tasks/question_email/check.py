from minicode.evals import EvalContext, contains_all, contains_any


def check(ctx: EvalContext) -> tuple[bool, str]:
    answer = ctx.final_text
    if not contains_all(answer, ["is_valid_email", "validators.py"]):
        return False, "answer does not name is_valid_email in validators.py"
    if not contains_any(answer, ["2 ", "two", "{2,}", "at least 2"]):
        return False, "answer does not state the 2-letter minimum for the TLD"
    return True, "names the function, the file and the TLD rule"
