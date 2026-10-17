---
name: changelog-entry
description: This project's rule for recording changes. Use it whenever you change any code in this repository.
---

# Recording a change

Every code change must be recorded in `CHANGELOG.md`, in the `## Unreleased` section (create it
at the top if it is missing). Add exactly one line per change, in this format:

    - <type>: <short description in lowercase>

where `<type>` is one of `feat`, `fix`, `refactor`, `docs`. Example:

    - fix: correct rounding in totals

Do not edit the sections of released versions.
