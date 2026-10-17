from minicode.evals import EvalContext, run_pytest


def check(ctx: EvalContext) -> tuple[bool, str]:
    leftovers = [
        path.relative_to(ctx.workspace).as_posix()
        for path in ctx.workspace.rglob("*.py")
        if "calc_total" in path.read_text(encoding="utf-8")
    ]
    if leftovers:
        return False, f"calc_total still in: {', '.join(leftovers)}"
    pricing = (ctx.workspace / "shop" / "pricing.py").read_text(encoding="utf-8")
    if "def compute_total(" not in pricing:
        return False, "compute_total is not defined in shop/pricing.py"
    return run_pytest(ctx.workspace)
