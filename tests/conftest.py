import shutil
from pathlib import Path

import pytest

from app.config import ROOT


@pytest.fixture(autouse=True)
def clean_environment(tmp_path, monkeypatch):
    """Every test starts clean and writes its run folders to a temp dir, never into your real runs/ folder."""
    monkeypatch.setenv("RUNS_DIR", str(tmp_path / "runs"))
    for var in ("AGENT_DIR", "PROMPTS_DIR", "WORKSPACE_DIR", "A2A_TOKEN", "ALLOW_ANY_HOST", "TRACE_CONTENT",
                "OTEL_EXPORTER_OTLP_ENDPOINT", "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    """A throw-away copy of the sample input files so tests never touch your real files."""
    ws = tmp_path / "workspace"
    shutil.copytree(ROOT / "my_agent" / "workspace", ws, ignore=shutil.ignore_patterns("output"))
    monkeypatch.setenv("WORKSPACE_DIR", str(ws))
    return ws


@pytest.fixture
def make_agent(tmp_path, monkeypatch):
    """Build a temporary AGENT folder (a copy of my_agent) with the tools / rules / MCP servers you ask for, and point the app at it."""
    def make(*tools: str, guardrails: str | None = None, mcp: str | None = None) -> Path:
        agent = tmp_path / "agent"
        if not agent.exists():
            shutil.copytree(ROOT / "my_agent", agent, ignore=shutil.ignore_patterns("workspace", "BLUEPRINT.md", "README.md"))
        (agent / "agent.toml").write_text("[agent]\nname='Test Agent'\n[tools]\nenabled=[" + ",".join(f"'{t}'" for t in tools) + "]\n")
        if guardrails is not None:
            (agent / "guardrails.toml").write_text(guardrails)
        if mcp is not None:
            (agent / "mcp.json").write_text(mcp)
        monkeypatch.setenv("AGENT_DIR", str(agent))
        return agent
    return make


@pytest.fixture
def agent_toml(make_agent):
    """Short form: agent_toml('list_files', 'run_command') enables those tools."""
    return make_agent
