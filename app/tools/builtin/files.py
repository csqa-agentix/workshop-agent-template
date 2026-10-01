"""Built-in tools: look around and read/write files inside the workspace folder."""
from __future__ import annotations

import difflib
import re

from app.tools._sandbox import is_denied, relative, resolve
from app.tools.registry import tool

SKIP = {".git", "__pycache__", ".venv", "node_modules"}


@tool
def list_files(path: str = ".") -> str:
    """List the files and folders inside a workspace folder (use '.' for the top). Start here to see what exists."""
    folder = resolve(path)
    if not folder.is_dir():
        raise ValueError(f"'{path}' is not a folder.")
    rows = [f"{relative(p)}{'/' if p.is_dir() else f'  ({p.stat().st_size} bytes)'}"
            for p in sorted(folder.iterdir()) if p.name not in SKIP and not is_denied(p)]
    return "\n".join(rows) or "(empty folder)"


@tool
def read_file(path: str, start_line: int = 1, max_lines: int = 200) -> str:
    """Read a text file from the workspace, with line numbers. For big files read a slice using start_line and max_lines."""
    file = resolve(path)
    if not file.is_file():
        raise ValueError(f"'{path}' is not a file. Call list_files to see what exists.")
    max_lines = min(max_lines, 500)                       # keep answers small
    lines = file.read_text(encoding="utf-8", errors="replace").splitlines()
    chunk = lines[start_line - 1: start_line - 1 + max_lines]
    body = "\n".join(f"{start_line + i:>4}| {line}" for i, line in enumerate(chunk))
    more = len(lines) - (start_line - 1 + len(chunk))
    return f"{relative(file)} ({len(lines)} lines)\n{body}" + (f"\n… {more} more lines. Call again with start_line={start_line + len(chunk)}." if more > 0 else "")


@tool
def search_text(pattern: str, path: str = ".") -> str:
    """Search for a regular expression in the files under a workspace folder. Returns 'file:line: text' matches (max 50)."""
    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as exc:
        raise ValueError(f"Invalid pattern: {exc}") from exc
    root = resolve(path)
    files = [root] if root.is_file() else [p for p in sorted(root.rglob("*")) if p.is_file() and not SKIP & set(p.parts) and not is_denied(p)]
    hits: list[str] = []
    for file in files:
        try:
            for n, line in enumerate(file.read_text(encoding="utf-8").splitlines(), 1):
                if regex.search(line):
                    hits.append(f"{relative(file)}:{n}: {line.strip()[:160]}")
        except UnicodeDecodeError:
            continue                                      # skip binary files
    return "\n".join(hits[:50]) + (f"\n… {len(hits) - 50} more matches" if len(hits) > 50 else "") if hits else "No matches."


@tool
def write_file(path: str, content: str) -> str:
    """Create or overwrite a text file in the workspace. Guardrails decide which folders are writable (default: output/)."""
    file = resolve(path)
    file.parent.mkdir(parents=True, exist_ok=True)
    file.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} characters to {relative(file)}"


@tool
def edit_file(path: str, old_text: str, new_text: str) -> str:
    """Change a file by replacing ONE exact piece of text (old_text must appear exactly once) and show the diff. Prefer this over rewriting a whole file. Guardrails decide which files are editable."""
    file = resolve(path)
    if not file.is_file():
        raise ValueError(f"'{path}' is not a file. Call list_files to see what exists.")
    before = file.read_text(encoding="utf-8")
    found = before.count(old_text)
    if found != 1:
        raise ValueError(f"old_text must appear exactly once in {path}, but it appears {found} times. Use a longer, unique piece of text.")
    after = before.replace(old_text, new_text)
    file.write_text(after, encoding="utf-8")
    diff = "".join(difflib.unified_diff(before.splitlines(True), after.splitlines(True), f"a/{path}", f"b/{path}", n=2))
    return f"Edited {relative(file)}\n{diff}"
