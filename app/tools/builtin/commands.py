"""Built-in tool: run ONE pre-approved kind of command inside the workspace (tests, a linter, `git diff` …).

Not switched on by default: add "run_command" to [tools].enabled in my_agent/agent.toml, and list exactly the commands
your agent needs in my_agent/guardrails.toml under [commands] allowed (a command is allowed when it STARTS WITH an entry).

Safety layers: (1) allow-list by command prefix  (2) no shell, so `;`, `&&`, `|` do nothing  (3) arguments that
point outside the workspace (`/etc`, `~`, `../`) are refused  (4) 60-second timeout  (5) a human is asked first
(guardrails.toml [approval])  (6) the command never sees your API key.
Honest limit: a program you allow can still do whatever that program can do. Allow the narrowest command you can.
"""
from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys

from app.config import load_rules
from app.tools._sandbox import workspace
from app.tools.registry import tool

SECRET_NAME = re.compile(r"(?i)(key|token|secret|passw|credential|auth)")
TIMEOUT_SECONDS = 60


def _allowed(parts: list[str]) -> bool:
    return any(parts[: len(entry.split())] == entry.split() for entry in load_rules().allowed_commands)


def _escapes_workspace(arg: str) -> bool:
    return arg.startswith(("/", "~")) or arg == ".." or "../" in arg or "..\\" in arg


@tool
def run_command(command: str) -> str:
    """Run one of the pre-approved commands in the workspace folder (for example 'pytest -q') and return its real output and exit code. A human may be asked to approve each run."""
    parts = shlex.split(command)
    if not parts or not _allowed(parts):
        raise ValueError(f"Command not allowed. Allowed commands start with: {list(load_rules().allowed_commands) or 'nothing yet – add some under [commands] allowed in my_agent/guardrails.toml'}")
    if any(_escapes_workspace(a) for a in parts[1:]):
        raise ValueError("Arguments may not point outside the workspace (no absolute paths, '~' or '../').")
    if parts[0] == "pytest":
        parts = [sys.executable, "-m", "pytest", *parts[1:]]
    elif parts[0] == "python":
        parts[0] = sys.executable
    try:
        clean_env = {k: v for k, v in os.environ.items() if not SECRET_NAME.search(k)}      # belt and braces: no secrets in the child
        done = subprocess.run(parts, cwd=workspace(), capture_output=True, text=True, timeout=TIMEOUT_SECONDS, env=clean_env)
    except FileNotFoundError:
        raise ValueError(f"Program '{parts[0]}' is not installed on this machine.") from None
    except subprocess.TimeoutExpired:
        return f"exit_code: TIMEOUT after {TIMEOUT_SECONDS}s"
    return f"exit_code: {done.returncode}\n--- stdout ---\n{done.stdout[-3000:]}\n--- stderr ---\n{done.stderr[-1500:]}"
