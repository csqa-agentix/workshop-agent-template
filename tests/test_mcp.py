"""External MCP servers (Playwright / GitHub / your own): include filter, approvals, secrets, remote URLs."""
import asyncio
import json
import os
import socket
import subprocess
import sys
import time
from pathlib import Path

import pytest

from app.config import ROOT
from app.mcp_client import ToolHub, ToolHubError

FAKE = str(Path(__file__).parent / "fixtures" / "fake_mcp_server.py")


def stdio_server(**extra) -> dict:
    return {"command": "python", "args": [FAKE], **extra}


def hub_for(make_agent, mcp: dict, workspace: Path):
    make_agent("list_files", mcp=json.dumps({"mcpServers": mcp}))
    return ToolHub.for_agent(extra_env={"WORKSPACE_DIR": str(workspace), "AGENT_DIR": os.environ["AGENT_DIR"]})


def run(coro):
    return asyncio.run(coro)


def test_only_included_tools_reach_the_model(make_agent, workspace):
    async def go():
        async with hub_for(make_agent, {"fake": stdio_server(include=["echo", "add"])}, workspace) as hub:
            return hub.names(), hub.describe()
    names, info = run(go())
    assert names == ["add", "echo", "list_files"]                            # leak / dangerous / snapshot are NOT exposed
    fake = next(i for i in info if i["server"] == "fake")
    assert fake["tools_offered"] == 5 and fake["tools_exposed"] == ["echo", "add"]


def test_a_server_without_include_exposes_nothing_and_says_why(make_agent, workspace):
    async def go():
        async with hub_for(make_agent, {"fake": stdio_server()}, workspace) as hub:
            return hub.names(), [i["warning"] for i in hub.describe()]
    names, warnings = run(go())
    assert names == ["list_files"] and any("NO tools are included" in w for w in warnings)


def test_unknown_included_tool_lists_what_exists(make_agent, workspace):
    async def go():
        async with hub_for(make_agent, {"fake": stdio_server(include=["nope"])}, workspace):
            pass
    with pytest.raises(ToolHubError, match="echo"):
        run(go())


def test_external_tools_ask_for_approval_by_default(make_agent, workspace):
    async def go():
        async with hub_for(make_agent, {"fake": stdio_server(include=["echo", "add"], auto_approve=["add"])}, workspace) as hub:
            return hub.needs_approval("echo"), hub.needs_approval("add"), hub.needs_approval("list_files")
    echo, add, local = run(go())
    assert echo and not add and not local

    async def go2():
        async with hub_for(make_agent, {"fake": stdio_server(include=["echo"], approval="never")}, workspace) as hub:
            return hub.needs_approval("echo")
    assert run(go2()) is False


def test_awkward_tool_names_are_made_safe_and_prefixes_work(make_agent, workspace):
    async def go():
        async with hub_for(make_agent, {"fake": stdio_server(include=["browser.snapshot", "echo"], prefix="pw_")}, workspace) as hub:
            return hub.names(), await hub.call("pw_browser_snapshot", {}), await hub.call("pw_echo", {"text": "hi"})
    names, snap, echo = run(go())
    assert "pw_browser_snapshot" in names and snap == "page snapshot" and echo == "echo: hi"


def test_name_clash_is_explained(make_agent, workspace):
    async def go():
        async with hub_for(make_agent, {"a": stdio_server(include=["echo"]), "b": stdio_server(include=["echo"])}, workspace):
            pass
    with pytest.raises(ToolHubError, match="prefix"):
        run(go())


def test_secrets_from_env_are_expanded_never_stored_and_blanked(make_agent, workspace, monkeypatch):
    monkeypatch.setenv("FAKE_SECRET", "s3cr3t-value-abcdef")
    # a tool result containing the secret must come back redacted, because the hub registered the value
    async def go():
        server = stdio_server(include=["echo"], env={"X_SECRET": "${FAKE_SECRET}"})
        async with hub_for(make_agent, {"fake": server}, workspace) as hub:
            from app.guardrails import redact
            return redact("log line with s3cr3t-value-abcdef inside")
    assert run(go()) == "log line with [REDACTED] inside"


def test_missing_variable_is_a_friendly_error(make_agent, workspace, monkeypatch):
    monkeypatch.delenv("NOT_SET_ANYWHERE", raising=False)
    async def go():
        async with hub_for(make_agent, {"fake": stdio_server(include=["echo"], env={"K": "${NOT_SET_ANYWHERE}"})}, workspace):
            pass
    with pytest.raises(ToolHubError, match="NOT_SET_ANYWHERE.*\\.env"):
        run(go())


def test_secret_looking_tool_output_is_redacted_by_the_guardrails(make_agent, workspace):
    from app.guardrails import Guardrails

    async def go():
        async with hub_for(make_agent, {"fake": stdio_server(include=["leak"])}, workspace) as hub:
            return Guardrails().sanitize_output(await hub.call("leak", {}))
    assert "LLLL" not in run(go())


def test_a_wrong_program_name_is_explained(make_agent, workspace):
    async def go():
        async with hub_for(make_agent, {"x": {"command": "definitely-not-installed-xyz", "include": ["a"]}}, workspace):
            pass
    with pytest.raises(ToolHubError, match="not installed"):
        run(go())


def test_optional_servers_that_cannot_connect_are_skipped(make_agent, workspace):
    async def go():
        spec = {"url": "http://127.0.0.1:9/mcp", "include": ["a"], "optional": True}      # nothing listens on port 9
        async with hub_for(make_agent, {"x": spec}, workspace) as hub:
            return hub.names(), [i["warning"] for i in hub.describe()]
    names, warnings = run(go())
    assert names == ["list_files"] and any("skipped (optional)" in w for w in warnings)


# ── a REMOTE server over HTTP with a bearer token (like GitHub's) ─────────────────────────────
@pytest.fixture
def remote_server():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    proc = subprocess.Popen([sys.executable, FAKE, "http", str(port)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    for _ in range(80):
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.2).close()
            break
        except OSError:
            time.sleep(0.1)
    yield f"http://127.0.0.1:{port}/mcp"
    proc.terminate()
    proc.wait(timeout=5)


def test_remote_http_server_with_token_from_env(make_agent, workspace, remote_server, monkeypatch):
    monkeypatch.setenv("FAKE_TOKEN", "test-token-123456")

    async def go():
        spec = {"url": remote_server, "headers": {"Authorization": "Bearer ${FAKE_TOKEN}"}, "include": ["echo", "add"]}
        async with hub_for(make_agent, {"remote": spec}, workspace) as hub:
            return hub.names(), await hub.call("add", {"a": 2, "b": 40}), hub.describe()
    names, total, info = run(go())
    assert "echo" in names and total == "42"
    assert next(i for i in info if i["server"] == "remote")["transport"] == "http"
    assert "test-token" not in json.dumps(info)                              # the manifest never holds the token


def test_remote_server_with_wrong_token_fails_clearly(make_agent, workspace, remote_server, monkeypatch):
    monkeypatch.setenv("FAKE_TOKEN", "wrong")

    async def go():
        spec = {"url": remote_server, "headers": {"Authorization": "Bearer ${FAKE_TOKEN}"}, "include": ["echo"]}
        async with hub_for(make_agent, {"remote": spec}, workspace):
            pass
    with pytest.raises(ToolHubError, match="remote.*401.*token"):
        run(go())


def test_the_whole_agent_can_use_an_external_tool_after_approval(make_agent, workspace):
    from app.agent_loop import run_agent
    from app.guardrails import Guardrails
    from app.llm_client import ScriptedLLM
    from app.trace import Trace

    llm = ScriptedLLM([{"calls": [{"tool": "echo", "args": {"text": "hello"}}, {"tool": "dangerous", "args": {}}]}, {"say": "done"}])

    async def go(answer: bool, tmp):
        async def approve(tool, args):
            return answer
        async with hub_for(make_agent, {"fake": stdio_server(include=["echo"])}, workspace) as hub:
            trace = Trace(tmp, quiet=True)
            await run_agent(goal="g", system_prompt="p", llm=llm, hub=hub, guard=Guardrails(), trace=trace, max_turns=4, approve=approve)
            return [e["summary"] for e in trace.events if e["kind"] == "observe"]
    import tempfile
    out = run(go(True, Path(tempfile.mkdtemp())))
    assert any("echo: hello" in o for o in out) and any("unknown tool" in o for o in out)   # 'dangerous' was never included, so it does not exist
    llm.i = 0
    denied = run(go(False, Path(tempfile.mkdtemp())))
    assert any(o.startswith("DENIED") for o in denied) and not any("echo: hello" in o for o in denied)
