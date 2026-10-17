# buggy_calculator

A tiny Python package with three deliberate bugs, used as minicode's end-to-end demo.

```bash
pytest -q          # 3 tests fail
uv run minicode run "Fix the failing tests" --cwd examples/buggy_calculator
```

To reset after a demo run: `git checkout -- examples/buggy_calculator`.
