"""Filesystem tools: read_file, list_dir, glob, grep, write_file, edit_file.

Every path the model gives us goes through `resolve_in_workspace`, which is the
workspace sandbox: after resolving `..` and symlinks, the result must still be
inside the workspace root, otherwise the call fails. It lives here, at the point
of use, so no filesystem tool can forget to apply it.

Descriptions and Field descriptions are written *for the model*: they are the
only documentation it gets, so they say when to use the tool and what to expect.
"""

from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from minicode.tools.base import Tool, ToolError

IGNORED_DIRS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}
MAX_LINE_CHARS = 2000
MAX_LIST_ENTRIES = 500
MAX_GLOB_RESULTS = 200
MAX_GREP_MATCHES = 200
MAX_GREP_FILE_BYTES = 1_000_000


# --- Sandbox and file helpers --------------------------------------------------


def resolve_in_workspace(root: Path, path: str) -> Path:
    """Resolve `path` against `root` and refuse anything that ends up outside it.

    `Path.resolve()` collapses `..` and follows symlinks, so `../x`, absolute
    paths elsewhere, and symlinks pointing out of the workspace are all caught.
    """
    root = root.resolve()
    candidate = (root / path).resolve()
    if not candidate.is_relative_to(root):
        raise ToolError(
            f"Path '{path}' is outside the workspace ({root}). "
            "Use a path relative to the workspace root."
        )
    return candidate


def read_text(path: Path) -> str:
    """Read a text file without changing its newlines; refuse binary files."""
    data = path.read_bytes()
    if b"\0" in data[:8192]:
        raise ToolError(f"'{path.name}' looks like a binary file; only text files can be read.")
    return data.decode("utf-8", errors="replace")


def write_text(path: Path, text: str) -> None:
    """Write exactly `text` (no newline translation, so LF/CRLF stay as given)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(text.encode("utf-8"))


def is_ignored(path: Path, root: Path) -> bool:
    return any(part in IGNORED_DIRS for part in path.relative_to(root).parts)


# --- Input models (their JSON schema is what the model sees) ------------------


class ReadFileArgs(BaseModel):
    path: str = Field(description="File path relative to the workspace root.")
    offset: int = Field(default=1, ge=1, description="1-based line number to start from.")
    limit: int = Field(default=300, ge=1, le=500, description="Maximum number of lines to return.")


class ListDirArgs(BaseModel):
    path: str = Field(default=".", description="Directory relative to the workspace root.")


class GlobArgs(BaseModel):
    pattern: str = Field(description="Glob pattern, e.g. '**/*.py' or 'src/*.toml'.")
    path: str = Field(default=".", description="Directory to search from.")


class GrepArgs(BaseModel):
    pattern: str = Field(description="Python regular expression to search for.")
    path: str = Field(default=".", description="File or directory to search in.")
    include: str = Field(
        default="*", description="Only search files matching this glob, e.g. '*.py'."
    )
    ignore_case: bool = Field(default=False, description="Case-insensitive match.")


class WriteFileArgs(BaseModel):
    path: str = Field(description="File path relative to the workspace root.")
    content: str = Field(description="The full new content of the file.")


class EditFileArgs(BaseModel):
    path: str = Field(description="File path relative to the workspace root.")
    old_string: str = Field(
        description="Exact text to replace, copied from the file including whitespace and "
        "indentation. Must appear exactly once: include enough surrounding lines to be unique."
    )
    new_string: str = Field(description="Replacement text.")


# --- The tools -----------------------------------------------------------------


class FileTools:
    """Filesystem tools bound to one workspace root."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()

    def tools(self) -> list[Tool]:
        return [
            Tool("read_file", READ_FILE_DOC, ReadFileArgs, self.read_file, "read"),
            Tool("list_dir", LIST_DIR_DOC, ListDirArgs, self.list_dir, "read"),
            Tool("glob", GLOB_DOC, GlobArgs, self.glob, "read"),
            Tool("grep", GREP_DOC, GrepArgs, self.grep, "read"),
            Tool("write_file", WRITE_FILE_DOC, WriteFileArgs, self.write_file, "write"),
            Tool("edit_file", EDIT_FILE_DOC, EditFileArgs, self.edit_file, "write"),
        ]

    def _resolve(self, path: str) -> Path:
        return resolve_in_workspace(self.root, path)

    def _display(self, path: Path) -> str:
        return path.relative_to(self.root).as_posix() or "."

    def _existing_file(self, path: str) -> Path:
        resolved = self._resolve(path)
        if not resolved.is_file():
            raise ToolError(
                f"File not found: '{path}'. Use list_dir or glob to find the right path."
            )
        return resolved

    def read_file(self, args: ReadFileArgs) -> str:
        lines = read_text(self._existing_file(args.path)).splitlines()
        if not lines:
            return f"(empty file: {args.path})"
        if args.offset > len(lines):
            raise ToolError(
                f"offset {args.offset} is past the end of the file ({len(lines)} lines)."
            )
        selected = lines[args.offset - 1 : args.offset - 1 + args.limit]
        numbered = [
            f"{number:>6}\t{line[:MAX_LINE_CHARS]}"
            for number, line in enumerate(selected, start=args.offset)
        ]
        end = args.offset + len(selected) - 1
        if args.offset > 1 or end < len(lines):
            numbered.append(
                f"(showing lines {args.offset}-{end} of {len(lines)}; use offset to read more)"
            )
        return "\n".join(numbered)

    def list_dir(self, args: ListDirArgs) -> str:
        directory = self._resolve(args.path)
        if not directory.is_dir():
            raise ToolError(f"Not a directory: '{args.path}'.")
        entries = sorted(directory.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower()))
        names = [f"{p.name}/" if p.is_dir() else p.name for p in entries[:MAX_LIST_ENTRIES]]
        if len(entries) > MAX_LIST_ENTRIES:
            names.append(f"({len(entries) - MAX_LIST_ENTRIES} more entries not shown)")
        return "\n".join(names) if names else f"(empty directory: {args.path})"

    def glob(self, args: GlobArgs) -> str:
        base = self._resolve(args.path)
        try:
            found = sorted(base.glob(args.pattern))
        except (ValueError, NotImplementedError) as exc:
            raise ToolError(f"Invalid glob pattern '{args.pattern}': {exc}") from exc
        # The pattern itself may contain '..', so re-check every result against the sandbox.
        matches = [
            self._display(p)
            for p in found
            if p.resolve().is_relative_to(self.root) and not is_ignored(p.resolve(), self.root)
        ]
        if not matches:
            return f"No files match '{args.pattern}' in '{args.path}'."
        shown = matches[:MAX_GLOB_RESULTS]
        if len(matches) > MAX_GLOB_RESULTS:
            shown.append(f"({len(matches) - MAX_GLOB_RESULTS} more matches not shown)")
        return "\n".join(shown)

    def grep(self, args: GrepArgs) -> str:
        flags = re.IGNORECASE if args.ignore_case else 0
        try:
            regex = re.compile(args.pattern, flags)
        except re.error as exc:
            raise ToolError(f"Invalid regular expression '{args.pattern}': {exc}") from exc
        results: list[str] = []
        for file in self._grep_candidates(args):
            results.extend(self._grep_file(file, regex))
            if len(results) >= MAX_GREP_MATCHES:
                results = results[:MAX_GREP_MATCHES]
                results.append(f"(stopped after {MAX_GREP_MATCHES} matches; narrow the search)")
                break
        return "\n".join(results) if results else f"No matches for '{args.pattern}'."

    def _grep_candidates(self, args: GrepArgs) -> list[Path]:
        base = self._resolve(args.path)
        if base.is_file():
            return [base]
        if not base.is_dir():
            raise ToolError(f"Path not found: '{args.path}'.")
        return sorted(p for p in base.rglob(args.include) if self._is_searchable(p))

    def _is_searchable(self, path: Path) -> bool:
        # resolve() so a symlink pointing outside the workspace is never read.
        resolved = path.resolve()
        return (
            path.is_file()
            and resolved.is_relative_to(self.root)
            and not is_ignored(resolved, self.root)
            and path.stat().st_size <= MAX_GREP_FILE_BYTES
        )

    def _grep_file(self, file: Path, regex: re.Pattern[str]) -> list[str]:
        try:
            lines = read_text(file).splitlines()
        except ToolError:
            return []  # binary files are silently skipped
        name = self._display(file)
        return [
            f"{name}:{n}: {line[:300]}" for n, line in enumerate(lines, 1) if regex.search(line)
        ]

    def write_file(self, args: WriteFileArgs) -> str:
        path = self._resolve(args.path)
        if path.is_dir():
            raise ToolError(f"'{args.path}' is a directory.")
        existed = path.exists()
        write_text(path, args.content)
        action = "Overwrote" if existed else "Created"
        return f"{action} {self._display(path)} ({len(args.content.splitlines())} lines)."

    def edit_file(self, args: EditFileArgs) -> str:
        path = self._existing_file(args.path)
        if not args.old_string:
            raise ToolError("old_string is empty. To create or overwrite a file, use write_file.")
        if args.old_string == args.new_string:
            raise ToolError("old_string and new_string are identical; nothing to change.")
        raw = read_text(path)
        # Models write '\n'. Normalize CRLF files for matching, then restore their style.
        crlf = "\r\n" in raw
        text = raw.replace("\r\n", "\n") if crlf else raw
        count = text.count(args.old_string)
        if count == 0:
            raise ToolError(
                f"old_string not found in '{args.path}'. Read the file again and copy the "
                "exact text, including indentation and whitespace."
            )
        if count > 1:
            raise ToolError(
                f"old_string appears {count} times in '{args.path}'. Include more surrounding "
                "lines so it matches exactly one place."
            )
        updated = text.replace(args.old_string, args.new_string, 1)
        write_text(path, updated.replace("\n", "\r\n") if crlf else updated)
        line = text[: text.index(args.old_string)].count("\n") + 1
        return f"Edited {self._display(path)} at line {line}."


READ_FILE_DOC = (
    "Read a text file. Returns lines prefixed with their line number (the number and a tab "
    "are not part of the file). Use offset/limit to page through long files. Always read a "
    "file before editing it."
)
LIST_DIR_DOC = "List the entries of a directory (non-recursive). Directories end with '/'."
GLOB_DOC = (
    "Find files by name pattern, e.g. '**/*.py'. Returns paths relative to the workspace. "
    "Skips .git, virtualenvs and caches."
)
GREP_DOC = (
    "Search file contents with a regular expression. Returns 'path:line: text' for each "
    "matching line. Use 'include' to limit to certain files, e.g. '*.py'."
)
WRITE_FILE_DOC = (
    "Create a new file or completely overwrite an existing one with 'content'. For changing "
    "part of an existing file, prefer edit_file."
)
EDIT_FILE_DOC = (
    "Replace one exact occurrence of old_string with new_string in a file. old_string must "
    "match the file exactly (whitespace included) and be unique; read the file first and "
    "copy the text without the line-number prefix."
)
