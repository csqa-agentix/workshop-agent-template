"""Safety helper: tools may only touch files inside the workspace folder – and never credential files."""
from __future__ import annotations

import fnmatch
from pathlib import Path

from app.config import load_settings

# File names the agent can never read, even inside the workspace.
DENIED_NAMES = (".env", ".env.*", "*.pem", "*.key", "id_rsa*", "id_ed25519*", "*.pfx", ".netrc", ".git-credentials")


def workspace() -> Path:
    return load_settings().workspace_dir


def is_denied(path: Path) -> bool:
    return any(fnmatch.fnmatch(path.name.lower(), pattern) for pattern in DENIED_NAMES)


def resolve(path: str) -> Path:
    """Turn a relative path into a real path INSIDE the workspace, or raise a helpful error.
    `.resolve()` follows symlinks, so a link pointing outside the workspace is caught too."""
    root = workspace()
    target = (root / path).resolve()
    if target != root and root not in target.parents:
        raise ValueError(f"'{path}' is outside the workspace. Use paths relative to the workspace root.")
    if is_denied(target):
        raise ValueError(f"'{path}' is a protected credential file. Access denied.")
    return target


def relative(path: Path) -> str:
    return path.relative_to(workspace()).as_posix() or "."
