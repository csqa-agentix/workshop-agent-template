"""MODULE 12 · DOCTOR – "is my setup OK?" in one command.

    python -m app doctor          checks everything that does not need the internet
    python -m app doctor --live   ALSO makes one tiny call to the real model (tests your key + tool calling)

Every line says what was checked and, when something is wrong, exactly how to fix it.
"""
from __future__ import annotations

import asyncio
import importlib
import sys

from app.config import ROOT, agent_dir, load_profile, load_rules, load_settings


def _row(ok: bool | None, label: str, fix: str = "") -> bool:
    mark = {True: "✓", False: "✗", None: "·"}[ok]
    print(f"  {mark} {label}" + (f"\n      → {fix}" if fix and ok is False else ""))
    return ok is not False


async def _check_tools():
    from app.mcp_client import ToolHub
    try:
        env = {"WORKSPACE_DIR": str(load_settings().workspace_dir), "AGENT_DIR": str(agent_dir()), "PROMPTS_DIR": str(load_settings().prompts_dir)}
        async with ToolHub.for_agent(extra_env=env) as hub:
            return hub, hub.info, hub.names(), None
    except BaseException as exc:                                   # noqa: BLE001 – we want to show any failure
        return None, [], [], f"{exc}" if str(exc) else type(exc).__name__


def _live_check(s) -> bool:
    from app.llm_client import LLM, LLMError
    tools = [{"type": "function", "function": {"name": "get_number", "description": "Returns the secret number.",
                                                "parameters": {"type": "object", "properties": {}}}}]
    try:
        turn = LLM(s).complete([{"role": "user", "content": "Call the get_number tool to find the secret number."}], tools)
    except LLMError as exc:
        return _row(False, "Live model call", str(exc))
    except SystemExit as exc:
        return _row(False, "Live model call", str(exc))
    if turn.tool_calls and turn.tool_calls[0].name == "get_number":
        return _row(True, f"Live model call works and the model can call tools ({s.model})")
    return _row(False, "The model answered but did not call the tool", "Try THINKING=off or THINKING=on in .env, or another MODEL.")


def main(argv: list[str]) -> int:
    live = "--live" in argv
    s, profile, ok = load_settings(), load_profile(), True
    print("\nChecking your setup…\n")
    ok &= _row(sys.version_info >= (3, 11), f"Python {sys.version.split()[0]} (need 3.11 or newer)", "Install Python 3.11+ from python.org")
    for module, pip_name in (("openai", "openai"), ("mcp", "mcp"), ("a2a", "a2a-sdk[http-server]==1.2.1"), ("uvicorn", "uvicorn"), ("dotenv", "python-dotenv")):
        try:
            importlib.import_module(module)
            ok &= _row(True, f"Package '{module}' is installed")
        except ImportError:
            ok &= _row(False, f"Package '{module}' is missing", f"Run:  pip install -r requirements.txt   (or pip install '{pip_name}')")
    has_key = bool(s.api_key)
    if has_key:
        _row(True, "API key is set in .env")
    elif (ROOT / ".env").exists():
        _row(None, ".env exists but has no API key yet (fine for --offline; paste your NVIDIA key after NVIDIA_API_KEY= for the real model)")
    else:
        _row(None, "No .env file yet (fine for --offline; for the real model: copy .env.example to .env and paste your NVIDIA key)")
    folder = agent_dir()
    rel = folder.relative_to(ROOT) if folder.is_relative_to(ROOT) else folder
    ok &= _row((folder / "agent.toml").exists(), f"Agent folder: {rel}/", "Run from the project folder, or pass --agent <folder>")
    agent_md = s.prompts_dir / "agent.md"
    ok &= _row(agent_md.exists(), f"Job description found: {agent_md.relative_to(ROOT) if agent_md.is_relative_to(ROOT) else agent_md}", "Create my_agent/prompts/agent.md (copy templates/agent.blank.md)")
    try:
        rules = load_rules()
        ok &= _row(True, f"Guardrails loaded: may write {list(rules.writable)}, {len(rules.allowed_commands)} command(s) allowed")
    except Exception as exc:                                       # noqa: BLE001
        ok &= _row(False, "my_agent/guardrails.toml is not valid", str(exc))
        rules = None
    enabled = profile["tools"]["enabled"]
    ok &= _row(bool(enabled), f"Built-in/own tools enabled in agent.toml: {', '.join(enabled) or 'none'}", "List at least one tool under [tools] enabled in my_agent/agent.toml")
    hub, info, names, error = asyncio.run(_check_tools())
    if error:
        ok &= _row(False, "Tool servers (MCP) start", error)
    else:
        for i in info:
            label = f"MCP server '{i.name}' ({i.transport}): offers {len(i.offered)} tool(s)" + (f", agent gets: {', '.join(i.exposed)}" if i.exposed else ", agent gets none")
            ok &= _row(not i.warning, label, i.warning)
        missing = [t for t in enabled if t not in names]
        ok &= _row(not missing, f"Tools the model will see ({len(names)}): {', '.join(names)}",
                   f"my_agent/agent.toml lists tools that do not exist: {missing}. Built-ins: list_files, read_file, search_text, write_file, edit_file, run_command")
        limit = rules.max_tools if rules else 4
        ok &= _row(len(names) <= limit, f"Tool count {len(names)} (limit: {limit})", "Remove tools from agent.toml [tools].enabled or from the \"include\" list in mcp.json")
        ext = sum(1 for i in info if i.name != "local-tools")
        limit_mcp = rules.max_external_mcp if rules else 1
        ok &= _row(ext <= limit_mcp, f"External MCP servers: {ext} (limit: {limit_mcp})", "Remove servers from my_agent/mcp.json")
    ok &= _row(s.workspace_dir.is_dir(), f"Workspace (input files) folder exists: {s.workspace_dir}", "Create it, or pass --workspace <folder>")
    if live:
        ok &= _live_check(s) if has_key else _row(False, "Live model call", "Add your NVIDIA key to .env first")
    print("\n" + ("All good. Next:  python -m app --offline   (or without --offline for the real model)\n" if ok else "Fix the ✗ items above, then run  python -m app doctor  again.\n"))
    return 0 if ok else 1
