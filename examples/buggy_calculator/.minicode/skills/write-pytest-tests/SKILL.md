---
name: write-pytest-tests
description: How to write focused, readable pytest tests. Use when adding tests for new or changed code, or when asked to improve test coverage.
---

# Writing pytest tests

## Before writing
1. Read the code under test and the existing tests in `tests/` (naming, fixtures, style).
2. List the behaviours to cover: the normal case, edge cases (empty input, zero, negative,
   boundaries), and error cases (which exception, which message).

## Rules
- One behaviour per test. Name it after the behaviour: `test_median_of_even_length_averages_middle`.
- Arrange / act / assert, with a blank line between the parts when the test is longer than 3 lines.
- Use `pytest.raises(ExpectedError, match="...")` for errors, never a bare `try/except`.
- Use `pytest.mark.parametrize` for the same check on several inputs, not copy-pasted tests.
- Compare floats with `pytest.approx`.
- No randomness, no network, no sleeping. Use `tmp_path` for files.
- Do not test private helpers directly when the public function covers them.

## After writing
- Run only the new tests first (`pytest -q tests/test_x.py -k name`), then the whole suite.
- A new test for a bug fix must fail before the fix and pass after it. Say so in your summary.

See `example_test.py` in this folder for a template.
