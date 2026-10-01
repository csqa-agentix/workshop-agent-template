"""Security behaviour of the whole system, through the REAL MCP server."""
import asyncio
import os

from app.config import ROOT

import pytest

from app.mcp_client import ToolHub
from app.tools import _sandbox


def call(workspace, tool, args, env=None):
    async def go():
        async with ToolHub.for_agent(extra_env={"WORKSPACE_DIR": str(workspace), "AGENT_DIR": os.environ.get("AGENT_DIR", str(ROOT / "my_agent")), **(env or {})}) as hub:
            return await hub.call(tool, args)
    return asyncio.run(go())


def test_path_escape_is_refused(workspace):
    assert "outside the workspace" in call(workspace, "read_file", {"path": "../../etc/passwd"})


def test_symlink_escape_is_refused(workspace, tmp_path):
    secret = tmp_path / "outside.txt"
    secret.write_text("top secret")
    (workspace / "link.txt").symlink_to(secret)
    assert "outside the workspace" in call(workspace, "read_file", {"path": "link.txt"})


def test_credential_files_are_invisible_and_unreadable(workspace):
    (workspace / ".env").write_text("NVIDIA_API_KEY=whatever")
    (workspace / "server.pem").write_text("x")
    assert "protected credential file" in call(workspace, "read_file", {"path": ".env"})
    listing = call(workspace, "list_files", {"path": "."})
    assert ".env" not in listing and "server.pem" not in listing
    assert "whatever" not in call(workspace, "search_text", {"pattern": "whatever"})


def test_api_key_never_reaches_tools(workspace, monkeypatch, make_agent, tmp_path):
    """Even if a .env file with the key exists, the tool server and the commands it runs must not see it."""
    import os
    make_agent("run_command", guardrails='[commands]\nallowed = ["pytest"]\n')
    secret = "nvapi-" + "Z" * 30
    dotenv = tmp_path / "leaky.env"
    dotenv.write_text(f"NVIDIA_API_KEY={secret}\n")
    monkeypatch.setenv("NVIDIA_API_KEY", secret)
    (workspace / "test_env.py").write_text("import os\n\ndef test_env():\n    print('KEY=' + str(os.environ.get('NVIDIA_API_KEY')))\n")
    # DOTENV_PATH points the server at a .env that WOULD leak the key if the tool process loaded it
    out = call(workspace, "run_command", {"command": "pytest -s -q test_env.py"},
               env={"DOTENV_PATH": str(dotenv)})
    assert "KEY=None" in out and "ZZZZ" not in out


def test_placeholder_key_is_not_a_key(monkeypatch):
    from app.config import load_settings
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-paste-your-key-here")
    assert load_settings().api_key == ""


def test_denied_names_cover_common_secrets():
    from pathlib import Path
    for name in (".env", ".env.local", "id_rsa", "cert.pem", "a.key", ".netrc"):
        assert _sandbox.is_denied(Path(name)), name
    assert not _sandbox.is_denied(Path("notes.md"))


def test_traces_never_contain_secrets(tmp_path):
    from app.config import load_profile, load_rules, load_settings
    from app.telemetry import RunTelemetry
    run = tmp_path / "run"
    run.mkdir()
    tele = RunTelemetry(run, goal="use nvapi-" + "Q" * 30, origin=None, settings=load_settings(), profile=load_profile(), rules=load_rules(), offline=True)
    span = tele.start_tool(1, "write_file", {"path": "output/x", "content": "token nvapi-" + "Q" * 30}, "c1", "local-tools")
    tele.end_tool(span, "result with sk-" + "R" * 30, "allowed", "not_required", error=False)
    tele.finish("completed", answer="answer nvapi-" + "Q" * 30)
    for name in ("trace.jsonl", "run.json", "trace.html"):
        text = (run / name).read_text()
        assert "QQQQ" not in text and "RRRR" not in text, name
