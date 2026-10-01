"""MODULE 10 · RUNNER – "do one complete run". The CLI, the A2A server and the web UI all call THIS one function.

    goal in  →  copy of the workspace  →  start MCP tools  →  agent loop  →  report.md + result.json + changes.diff out

Keeping it in one place means every way of starting the agent behaves identically.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable

from app.agent_loop import RunResult, run_agent
from app.config import ROOT, load_profile, load_rules, load_settings
from app.guardrails import Guardrails, redact
from app.llm_client import LLM, ScriptedLLM
from app.mcp_client import LOCAL, ToolHub
from app.prompts.loader import build_system_prompt
from app.trace import Trace, tools_used
from app.telemetry import RunTelemetry
from app.workspace import diff_workspaces, prepare_workspace, publish_outputs

Approver = Callable[[str, dict], Awaitable[bool]]
JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


@dataclass
class RunOutcome:
    status: str
    answer: str
    structured: dict | None
    run_dir: Path
    report_path: Path
    result_path: Path
    changes: str
    outputs: list[Path]
    turns: int
    tool_calls: int
    tools_used: dict = field(default_factory=dict)


def extract_json(answer: str) -> dict | None:
    """If the final answer contains a ```json {...} ``` block (or is pure JSON), return it as a dict."""
    for candidate in (*JSON_BLOCK.findall(answer), answer.strip()):
        try:
            value = json.loads(candidate)
            if isinstance(value, dict):
                return value
        except json.JSONDecodeError:
            continue
    return None


def make_llm(offline: bool, prompts_dir: Path):
    if not offline:
        return LLM(load_settings())
    script = prompts_dir / "offline_script.json"
    if not script.exists():
        raise SystemExit(f"No offline script at {script}. Offline mode needs one next to the prompts.")
    return ScriptedLLM(json.loads(script.read_text(encoding="utf-8")))


async def run_once(goal: str, *, offline: bool = False, in_place: bool = False, approve: Approver | None = None,
                   sink: Callable[[dict], None] | None = None, quiet: bool = False, llm=None, origin: dict | None = None) -> RunOutcome:
    s, profile, rules = load_settings(), load_profile(), load_rules()
    trace = Trace(quiet=quiet, sink=sink)                         # creates runs/<id>/ FIRST, so even a failed start leaves a record
    tele = RunTelemetry(trace.run_dir, goal=goal, origin=origin, settings=s, profile=profile, rules=rules, offline=offline)
    result: RunResult | None = None
    status, error, changes, out_names, outputs = "crashed", None, "", [], []
    try:
        llm = llm or make_llm(offline, s.prompts_dir)
        s.workspace_dir.mkdir(parents=True, exist_ok=True)
        work = s.workspace_dir if in_place else prepare_workspace(s.workspace_dir, trace.run_dir / "workspace")
        env = {"WORKSPACE_DIR": str(work), "PROMPTS_DIR": str(s.prompts_dir), "SKILLS_MODE": s.skills_mode, "AGENT_DIR": str(s.agent_dir)}
        if not quiet:
            print(f"\nAgent '{profile['agent']['name']}' · run {trace.run_dir.name} · model: {'offline script' if offline else s.model}")
            print(f"GOAL: {goal}\n")
        async with ToolHub.for_agent(extra_env=env, max_chars=s.tool_output_max_chars) as hub:
            tele.set_tools(hub)
            names = hub.names()
            problems = [i.warning for i in hub.info if i.warning]
            if len(names) > rules.max_tools:
                problems.append(f"{len(names)} tools are active; the configured limit is {rules.max_tools} (my_agent/agent.toml → [tools].enabled, and \"include\" in mcp.json).")
            if hub.external_count > rules.max_external_mcp:
                problems.append(f"{hub.external_count} external MCP servers are configured; the configured limit is {rules.max_external_mcp} (my_agent/mcp.json).")
            local = next((i for i in hub.info if i.name == LOCAL), None)
            missing = [t for t in profile["tools"]["enabled"] if local and t not in local.exposed]
            if missing:
                raise SystemExit(f"my_agent/agent.toml lists tools that do not exist: {missing}. Available: {sorted(local.offered)}")
            if not quiet:
                print(f"Tools (served over MCP): {', '.join(names)}")
                for p in problems:
                    print(f"  ⚠ {p}")
                print()
            system_prompt = build_system_prompt(s.prompts_dir, max_turns=s.max_turns, skills_mode=s.skills_mode)
            tele.set_system_prompt(system_prompt)
            result = await run_agent(goal=goal, system_prompt=system_prompt, llm=llm, hub=hub, guard=Guardrails(rules),
                                     trace=trace, max_turns=s.max_turns, approve=approve, tele=tele)
        status = result.status
        changes = "" if in_place else diff_workspaces(s.workspace_dir, work)
        outputs = publish_outputs(work, trace.run_dir) if not in_place else []
        if changes:
            (trace.run_dir / "changes.diff").write_text(redact(changes), encoding="utf-8")
        out_names = [p.relative_to(trace.run_dir).as_posix() for p in outputs]
    except asyncio.CancelledError as exc:
        status, error = "cancelled", exc
        raise
    except BaseException as exc:                                  # includes Ctrl-C and SystemExit (e.g. missing API key)
        status, error = ("crashed" if isinstance(exc, KeyboardInterrupt) else "failed"), exc
        raise
    finally:
        tele.finish(status, answer=result.answer if result else None, error=error, outputs=out_names,
                    turns=result.turns if result else None)

    structured = extract_json(result.answer)
    used = tools_used(trace.events)
    report = trace.write_report(goal, result.status, result.answer, changes, out_names)
    result_path = trace.run_dir / "result.json"
    result_path.write_text(json.dumps({
        "agent": profile["agent"]["name"], "run_id": trace.run_dir.name, "goal": goal, "status": result.status,
        "answer": result.answer, "structured": structured, "turns": result.turns, "tool_calls": result.tool_calls,
        "tools_used": used, "guardrail_blocks": sum(1 for e in trace.events if e["kind"] == "guard"),
        "files_changed": sorted(set(re.findall(r"^\+\+\+ b/(.+)$", changes, re.MULTILINE))), "outputs": out_names,
    }, indent=2, ensure_ascii=False), encoding="utf-8")
    return RunOutcome(result.status, result.answer, structured, trace.run_dir, report, result_path, changes, outputs,
                      result.turns, result.tool_calls, used)
