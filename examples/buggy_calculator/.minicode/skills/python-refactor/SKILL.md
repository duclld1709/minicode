---
name: python-refactor
description: Safe, behaviour-preserving refactoring of Python code (renames, extracting functions, removing duplication). Use when asked to refactor, clean up, or rename something across files.
---

# Refactoring Python safely

A refactor changes structure, never behaviour. Work in small steps and keep the tests green.

## Steps
1. Run the test suite first and note the result. If tests already fail, report that before
   changing anything, so a pre-existing failure is not blamed on the refactor.
2. Find every usage before renaming: `grep` for the name with word boundaries, e.g. `\bold_name\b`,
   in code, tests, docs and config. Check `__init__.py` re-exports and string references.
3. Change one thing at a time with `edit_file`. After each logical step, run the tests.
4. Extract a function when a block has one clear purpose and a good name. Pass data in as
   parameters and return results; do not reach for globals.
5. Remove duplication only when the copies change for the same reason.

## Do not
- Mix a refactor with a behaviour change or a bug fix. If you find a bug, report it separately.
- Reformat unrelated code. It hides the real change in the diff.
- Leave the old name behind as an alias unless the user asks for backward compatibility.

## Summary to the user
List the renamed or moved symbols, the files touched, and the test command and result.
