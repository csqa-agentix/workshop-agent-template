"""MODULE 1 · ENTRY POINTS – three ways to start the same agent.

  1. Terminal      python -m app "your goal in plain English"
  2. Web page + A2A python -m app serve            (then open http://localhost:8000  – other programs call it over A2A)
  3. Any A2A client python -m app.a2a_client "your goal" --url http://localhost:8000
  +  Health check    python -m app doctor [--live]
  +  Past runs       python -m app runs [show|open|export|prune]

Handy flags:  --offline (no key/internet, scripted model)   --agent FOLDER   --workspace DIR   --yes   --in-place
"The agent" is a folder (default my_agent/). Try the dummy ones:  --agent examples/example-triage-report
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from app.config import ROOT

DEFAULT_GOAL = "Describe what is in the workspace and write a short summary to output/summary.md."


def add_shared_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--agent", help="the agent folder to run (default: my_agent). It holds agent.toml, prompts/, tools/, workspace/ …")
    p.add_argument("--example", help="shortcut for --agent examples/<name>")
    p.add_argument("--prompts", help="use a different prompt folder")
    p.add_argument("--workspace", help="use a different workspace folder (it is COPIED for every run; originals are never touched)")
    p.add_argument("--offline", action="store_true", help="scripted model: no key, no internet (tools/MCP/guardrails stay real)")
    p.add_argument("--yes", action="store_true", help="auto-approve actions that normally ask a human (use with care)")
    p.add_argument("--in-place", action="store_true", help="work directly in the workspace instead of on a copy")


def apply_environment(args) -> None:
    """Point the app at the right folders BEFORE settings are read."""
    folder = args.agent or (f"examples/{args.example}" if args.example else None)
    if folder:
        path = Path(folder) if Path(folder).is_absolute() else (ROOT / folder)
        if not (path / "agent.toml").exists():
            raise SystemExit(f"'{folder}' is not an agent folder (it has no agent.toml). Folders to try: my_agent, examples/example-triage-report")
        os.environ["AGENT_DIR"] = str(path.resolve())
    if args.prompts:
        os.environ["PROMPTS_DIR"] = str(Path(args.prompts).resolve())
    if args.workspace:
        os.environ["WORKSPACE_DIR"] = str(Path(args.workspace).resolve())
    os.environ["AUTO_APPROVE"] = "1" if args.yes else os.environ.get("AUTO_APPROVE", "")
    os.environ["OFFLINE"] = "1" if args.offline else os.environ.get("OFFLINE", "")
    os.environ["IN_PLACE"] = "1" if args.in_place else os.environ.get("IN_PLACE", "")


async def ask_human(tool: str, args: dict) -> bool:
    """Human-in-the-loop in the terminal: show exactly what the agent wants to do and wait for y/N."""
    if not sys.stdin.isatty():
        print(f"  [approval] {tool} {json.dumps(args)} -> denied (no terminal to ask; use --yes to allow)")
        return False
    print(f"\n  ⚠ The agent wants to run:  {tool} {json.dumps(args, ensure_ascii=False)}")
    return (await asyncio.to_thread(input, "  Allow? [y/N] ")).strip().lower() in ("y", "yes")


async def approve_all(tool: str, args: dict) -> bool:
    return True


def run_command_line(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m app", description="Run the agent in this terminal.")
    p.add_argument("goal", nargs="?", help="what the agent should achieve (plain English)")
    p.add_argument("--goal-file", help="read the goal from a file (default: goal.md inside the agent folder)")
    add_shared_flags(p)
    args = p.parse_args(argv)
    apply_environment(args)
    from app.config import agent_dir
    goal = args.goal
    if args.goal_file:
        goal = Path(args.goal_file).read_text(encoding="utf-8").strip()
    elif not goal and (agent_dir() / "goal.md").exists():
        goal = (agent_dir() / "goal.md").read_text(encoding="utf-8").strip()      # the agent folder's own goal.md
    goal = goal or DEFAULT_GOAL

    from app.llm_client import LLMError
    from app.runner import run_once
    try:
        outcome = asyncio.run(run_once(goal, offline=args.offline, in_place=args.in_place,
                                       approve=approve_all if args.yes else ask_human))
    except LLMError as exc:
        print(f"\nModel problem: {exc}")
        return 2
    print(f"\nStatus: {outcome.status.upper()} after {outcome.turns} turn(s), {outcome.tool_calls} tool call(s)")
    print(f"Report: {outcome.report_path}\nResult: {outcome.result_path}")
    if outcome.outputs:
        print("Files the agent produced:\n  " + "\n  ".join(str(p) for p in outcome.outputs))
    print()
    return 0 if outcome.status == "completed" else 1


def serve_command_line(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m app serve", description="Serve the agent over A2A (+ a web page) at a URL.")
    p.add_argument("--host", help="default from agent.toml (127.0.0.1 = this computer only)")
    p.add_argument("--port", type=int, help="default from agent.toml (8000)")
    add_shared_flags(p)
    args = p.parse_args(argv)
    apply_environment(args)
    from app.a2a_server import serve
    serve(host=args.host, port=args.port)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["serve"]:
        return serve_command_line(argv[1:])
    if argv[:1] == ["runs"]:
        from app.runs_cli import main as runs
        return runs(argv[1:])
    if argv[:1] == ["doctor"]:
        from app.doctor import main as doctor
        return doctor(argv[1:])
    return run_command_line(argv)


if __name__ == "__main__":
    sys.exit(main())
