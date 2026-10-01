"""MODULE 10 · RUN WORKSPACE – every run works on a throw-away COPY of your workspace folder.

Why: the agent can never damage your original files, two runs never disturb each other, and afterwards we can
show exactly what the agent changed (changes.diff). Your deliverables end up in  runs/<id>/output/.
"""
from __future__ import annotations

import difflib
import shutil
from pathlib import Path

SKIP_DIRS = {"node_modules", ".venv", "__pycache__", ".pytest_cache", "runs", "output", ".git"}
MAX_COPY_BYTES = 200 * 1024 * 1024


def _tree_size(root: Path) -> int:
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file() and not SKIP_DIRS & set(p.relative_to(root).parts))


def prepare_workspace(source: Path, target: Path, keep_git: bool = True) -> Path:
    """Copy `source` to `target` (skipping heavy/irrelevant folders) and return `target`."""
    if _tree_size(source) > MAX_COPY_BYTES:
        raise SystemExit(f"{source} is larger than {MAX_COPY_BYTES // 2**20} MB. Point --workspace at a smaller folder, or use --in-place.")
    skip = SKIP_DIRS - ({".git"} if keep_git else set())
    shutil.copytree(source, target, symlinks=True, ignore=shutil.ignore_patterns(*skip))
    (target / "output").mkdir(exist_ok=True)
    return target


def _text(path: Path) -> list[str] | None:
    try:
        if path.stat().st_size > 1_000_000:
            return None
        return path.read_text(encoding="utf-8").splitlines(keepends=True)
    except (UnicodeDecodeError, OSError):
        return None


def diff_workspaces(source: Path, work: Path) -> str:
    """Unified diff of every text file the agent changed, added or deleted (ignores output/)."""
    def files(root: Path) -> set[str]:
        return {p.relative_to(root).as_posix() for p in root.rglob("*")
                if p.is_file() and not p.is_symlink() and not SKIP_DIRS & set(p.relative_to(root).parts)}
    chunks = []
    for rel in sorted(files(source) | files(work)):
        a, b = source / rel, work / rel
        before = _text(a) if a.exists() else []
        after = _text(b) if b.exists() else []
        if before is None or after is None or before == after:
            continue
        chunks.append("".join(difflib.unified_diff(before, after, f"a/{rel}" if a.exists() else "/dev/null",
                                                   f"b/{rel}" if b.exists() else "/dev/null")))
    return "\n".join(chunks)


def publish_outputs(work: Path, run_dir: Path) -> list[Path]:
    """Copy workspace/output/ to runs/<id>/output/ (the place people will look) and list the files."""
    src, dst = work / "output", run_dir / "output"
    if src.is_dir():
        shutil.copytree(src, dst, dirs_exist_ok=True)
    return sorted(p for p in dst.rglob("*") if p.is_file() and p.name != ".gitkeep") if dst.is_dir() else []
