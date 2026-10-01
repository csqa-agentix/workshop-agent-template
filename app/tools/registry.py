"""MODULE 6 · TOOL REGISTRY – how a plain Python function becomes an agent tool.

To make a tool:   write a function in my_agent/tools/your_file.py and put @tool above it. That's it.

    @tool
    def add(a: int, b: int) -> str:
        '''Add two numbers.'''          # <- the model reads this sentence to decide WHEN to use the tool
        return str(a + b)

 • The docstring        = the tool's description for the model
 • The type hints       = the tool's argument schema for the model
 • The return value     = what the model sees afterwards (return a string; make it real output, never a guess)
 • raise ValueError("…") = a helpful error the model can read and recover from

Built-in tools live in app/tools/builtin/. YOUR tools live in my_agent/tools/ (files starting with "_" are ignored,
so _example_tool.py stays switched off until you rename it). Then list the tool's name in my_agent/agent.toml.
"""
from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from pathlib import Path
from typing import Callable

import app.tools as tools_package
from app.config import agent_dir

_REGISTERED: list[Callable] = []


def tool(fn: Callable) -> Callable:
    """Decorator: mark a function as an agent tool."""
    _REGISTERED.append(fn)
    return fn


_LOADED: set[tuple[str, int]] = set()


def discover() -> list[Callable]:
    """Import the built-in tools and the agent's own tools so their @tool functions register themselves."""
    for module in pkgutil.walk_packages(tools_package.__path__, prefix="app.tools."):
        if not module.name.rsplit(".", 1)[-1].startswith("_") and not module.ispkg:
            importlib.import_module(module.name)
    for file in sorted((agent_dir() / "tools").glob("*.py")):
        key = (str(file.resolve()), file.stat().st_mtime_ns)
        if not file.name.startswith("_") and key not in _LOADED:
            _LOADED.add(key)
            spec = importlib.util.spec_from_file_location(f"agent_tools.{file.stem}", file)
            spec.loader.exec_module(importlib.util.module_from_spec(spec))
    seen: dict[str, Callable] = {}
    for fn in _REGISTERED:
        seen[fn.__name__] = fn                    # a re-loaded file simply replaces its earlier version
    return list(seen.values())
