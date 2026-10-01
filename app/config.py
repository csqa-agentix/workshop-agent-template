"""MODULE 2 · CONFIG – where settings come from.

  .env                      secrets + model settings        (you edit; never share)
  my_agent/agent.toml       who the agent is, which tools   (you edit)
  my_agent/guardrails.toml  the rules it can't break        (you edit)

"The agent" is just a FOLDER (default: my_agent/). Run another one with  --agent examples/example-triage-report.
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
# The tool processes (MCP server and the commands it runs) must NEVER see your .env, so the agent sets NO_DOTENV=1 for them.
if not os.environ.get("NO_DOTENV"):
    load_dotenv(os.environ.get("DOTENV_PATH") or ROOT / ".env")


# Where the API key may live, in order. NVIDIA first because that is this template's default provider.
KEY_VARS = ("NVIDIA_API_KEY", "LLM_API_KEY", "OPENAI_API_KEY")


def real_key(value: str | None) -> str:
    """The API key, or "" if it is missing or still the placeholder from .env.example."""
    value = (value or "").strip()
    return "" if not value or "paste-your-key" in value else value


def agent_dir() -> Path:
    """The folder that holds one agent: agent.toml, prompts/, tools/, guardrails.toml, mcp.json, workspace/, goal.md."""
    return Path(os.environ.get("AGENT_DIR") or ROOT / "my_agent").resolve()


@dataclass(frozen=True)
class Settings:
    api_key: str
    model: str
    base_url: str
    thinking: str                 # off | low | on
    temperature: float
    top_p: float
    max_tokens: int
    max_turns: int                # hard stop for the agent loop
    min_seconds_between_calls: float   # polite spacing so the free tier does not rate-limit us
    max_retries: int
    timeout_seconds: float
    tool_output_max_chars: int    # long tool results are cut so the conversation stays small (= fewer tokens)
    skills_mode: str              # inline | on_demand
    agent_dir: Path               # the agent folder
    workspace_dir: Path           # the ONLY folder the file tools can see
    prompts_dir: Path
    trace_content: bool           # keep the text of model requests/replies in the run folder (redacted)


def load_settings() -> Settings:
    """Read settings fresh each time (so tests can change the environment)."""
    env = os.environ.get
    base = agent_dir()
    return Settings(
        api_key=next((real_key(env(n)) for n in KEY_VARS if real_key(env(n))), ""),
        model=env("MODEL", "nvidia/nemotron-3-super-120b-a12b"),
        base_url=env("BASE_URL", "https://integrate.api.nvidia.com/v1"),
        thinking=env("THINKING", "low"),
        temperature=float(env("TEMPERATURE", "1.0")),
        top_p=float(env("TOP_P", "0.95")),
        max_tokens=int(env("MAX_TOKENS", "4096")),
        max_turns=int(env("MAX_TURNS", "15")),
        min_seconds_between_calls=float(env("MIN_SECONDS_BETWEEN_CALLS", "1.6")),
        max_retries=int(env("MAX_RETRIES", "6")),
        timeout_seconds=float(env("TIMEOUT_SECONDS", "180")),
        tool_output_max_chars=int(env("TOOL_OUTPUT_MAX_CHARS", "6000")),
        skills_mode=env("SKILLS_MODE", "inline"),
        agent_dir=base,
        workspace_dir=Path(env("WORKSPACE_DIR") or base / "workspace").resolve(),
        prompts_dir=Path(env("PROMPTS_DIR") or base / "prompts").resolve(),
        trace_content=env("TRACE_CONTENT", "on").lower() not in ("off", "0", "false", "no"),
    )


def load_profile() -> dict:
    """my_agent/agent.toml: the agent's name, its A2A 'business card' and the tools it may use."""
    path = agent_dir() / "agent.toml"
    data = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    agent = {"name": "My Agent", "description": "A goal-driven AI agent.", "version": "0.1.0", **data.get("agent", {})}
    return {"agent": agent, "a2a_skills": data.get("a2a_skills", []),
            "tools": {"enabled": data.get("tools", {}).get("enabled", [])},
            "server": {"host": "127.0.0.1", "port": 8000, **data.get("server", {})}}


@dataclass(frozen=True)
class Rules:
    """The safety rules from my_agent/guardrails.toml (every field has a safe default)."""
    writable: tuple = ("output/",)                 # paths the agent may change: a folder "output/" or an exact file
    write_tools: tuple = ("write_file", "edit_file")
    blocked_tools: tuple = ()
    approval_tools: tuple = ("run_command",)       # a human must say yes before these run
    allowed_commands: tuple = ()                   # run_command may only START with one of these
    max_tool_calls: int = 40
    max_total_tokens: int = 250_000                # cost guard: tokens spent across the whole run
    max_context_tokens: int = 100_000              # size guard: how big the conversation itself may grow
    max_identical_calls: int = 2
    max_calls_per_tool: tuple = (("run_command", 12),)
    repeatable_tools: tuple = ("run_command",)
    max_write_chars: int = 100_000
    require_tool_evidence: bool = False
    claims_need_tool: tuple = ()                   # ((regex in the answer, tool that must have run first), …)
    max_tools: int = 4                             # a small, sharp toolset beats a large one
    max_external_mcp: int = 1                      # each extra MCP server is more surface to trust


def load_rules(path: Path | None = None) -> Rules:
    path = path or agent_dir() / "guardrails.toml"
    d = tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    files, cmds, appr, bud, claims = (d.get(k, {}) for k in ("files", "commands", "approval", "budgets", "claims"))
    ws = {**d.get("workshop", {}), **d.get("limits", {})}      # "[limits]" is the name; "[workshop]" still accepted
    base = Rules()
    per_tool = bud.get("per_tool", dict(base.max_calls_per_tool))
    return Rules(
        writable=tuple(files.get("writable", base.writable)),
        write_tools=tuple(files.get("write_tools", base.write_tools)),
        blocked_tools=tuple(d.get("tools", {}).get("blocked", base.blocked_tools)),
        approval_tools=tuple(appr.get("required_for", base.approval_tools)),
        allowed_commands=tuple(cmds.get("allowed", base.allowed_commands)),
        max_tool_calls=int(bud.get("max_tool_calls", base.max_tool_calls)),
        max_total_tokens=int(bud.get("max_total_tokens", base.max_total_tokens)),
        max_context_tokens=int(bud.get("max_context_tokens", base.max_context_tokens)),
        max_identical_calls=int(bud.get("max_identical_calls", base.max_identical_calls)),
        max_calls_per_tool=tuple(per_tool.items()),
        repeatable_tools=tuple(bud.get("repeatable_tools", base.repeatable_tools)),
        max_write_chars=int(files.get("max_write_chars", base.max_write_chars)),
        require_tool_evidence=bool(claims.get("require_tool_evidence", base.require_tool_evidence)),
        claims_need_tool=tuple((k, v) for k, v in claims.items() if k != "require_tool_evidence"),
        max_tools=int(ws.get("max_tools", base.max_tools)),
        max_external_mcp=int(ws.get("max_external_mcp", base.max_external_mcp)),
    )
