"""Tracing: every run leaves a complete, redacted, crash-safe record."""
import asyncio
import json
import threading
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

from app.llm_client import ScriptedLLM, Turn
from app.runner import run_once
from app.runs_cli import main as runs_cli
from app.telemetry import read_spans, runs_dir


def only_run() -> Path:
    runs = [p for p in runs_dir().iterdir() if p.is_dir()]
    assert len(runs) == 1
    return runs[0]


def test_a_run_leaves_the_full_record(workspace):
    outcome = asyncio.run(run_once("brief me", offline=True, quiet=True))
    run = outcome.run_dir
    for name in ("run.json", "trace.jsonl", "llm_calls.jsonl", "system_prompt.txt", "trace.html", "report.md", "result.json"):
        assert (run / name).exists(), name
    assert (runs_dir() / "index.html").exists()
    m = json.loads((run / "run.json").read_text())
    assert m["status"] == "completed" and m["entry"]["type"] == "cli" and m["usage"]["tool_calls"] == 7 and m["usage"]["guardrail_blocks"] == 1
    assert m["duration_s"] is not None and m["trace_id"] and len(m["trace_id"]) == 32
    assert any(k.endswith("prompts/agent.md") for k in m["fingerprints"]) and "system_prompt" in m["fingerprints"]
    assert m["tools"] == ["list_files", "read_file", "search_text", "write_file"] and m["mcp"][0]["server"] == "local-tools"
    spans = read_spans(run)
    names = [s["name"] for s in spans]
    assert names[0].startswith("invoke_agent") and any(n.startswith("chat ") for n in names) and "execute_tool read_file" in names
    assert all(s["finished"] for s in spans)
    root = spans[0]["attributes"]
    assert root["gen_ai.operation.name"] == "invoke_agent" and root["agent.status"] == "completed"
    tool = next(s for s in spans if s["name"] == "execute_tool write_file" and s["attributes"]["agent.guardrail.verdict"] == "blocked")
    assert any(e["name"] == "guardrail.blocked" for e in tool["events"])
    assert "Project Lighthouse" in (run / "trace.html").read_text()                      # the viewer carries its own data


def test_changing_a_prompt_changes_the_fingerprint(workspace, make_agent):
    agent = make_agent("list_files")
    first = asyncio.run(run_once("a", offline=True, quiet=True)).run_dir
    (agent / "prompts" / "agent.md").write_text((agent / "prompts" / "agent.md").read_text() + "\n- one more rule\n")
    second = asyncio.run(run_once("b", offline=True, quiet=True)).run_dir
    key = next(k for k in json.loads((first / "run.json").read_text())["fingerprints"] if k.endswith("prompts/agent.md"))
    assert json.loads((first / "run.json").read_text())["fingerprints"][key] != json.loads((second / "run.json").read_text())["fingerprints"][key]


class Exploding:
    """A model that fails on its second call."""
    def __init__(self, exc):
        self.exc, self.n = exc, 0

    def complete(self, messages, tools=None):
        self.n += 1
        if self.n == 1:
            from app.llm_client import ToolCall
            return Turn(tool_calls=[ToolCall("c1", "list_files", {"path": "."})], meta={"model": "boom"})
        raise self.exc


@pytest.mark.parametrize("exc,status", [(RuntimeError("the model service fell over"), "failed"), (KeyboardInterrupt(), "crashed")])
def test_a_crash_still_leaves_a_sealed_trace(workspace, exc, status):
    with pytest.raises(type(exc)):
        asyncio.run(run_once("x", quiet=True, llm=Exploding(exc)))
    run = only_run()
    m = json.loads((run / "run.json").read_text())
    assert m["status"] == status and m["ended_at"] and (status == "crashed" or "fell over" in m["error"]["message"])
    spans = read_spans(run)
    broken = [s for s in spans if s["name"].startswith("chat") and s["status"] == "ERROR"]
    assert broken and (run / "trace.html").exists()
    assert (run / "llm_calls.jsonl").read_text().count("\n") == 2                         # both model calls were logged, the failed one with its error


def test_a_missing_key_is_recorded_as_a_failed_run(workspace, monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    monkeypatch.setattr("app.config.real_key", lambda v: "")
    with pytest.raises(SystemExit):
        asyncio.run(run_once("x", quiet=True))
    m = json.loads((only_run() / "run.json").read_text())
    assert m["status"] == "failed" and "No API key" in m["error"]["message"]


def test_spans_that_never_finished_are_visible(tmp_path):
    (tmp_path / "trace.jsonl").write_text(json.dumps({"t": "start", "trace_id": "t", "span_id": "s1", "parent_id": None, "name": "chat x", "start_ns": 1, "attributes": {}}) + "\n"
                                          + '{"t": "start", "trace_id": "t", "span_id": "s2", "pa')            # killed mid-write
    spans = read_spans(tmp_path)
    assert len(spans) == 1 and spans[0]["finished"] is False


def test_content_can_be_switched_off(workspace, monkeypatch):
    monkeypatch.setenv("TRACE_CONTENT", "off")
    run = asyncio.run(run_once("secret plans", offline=True, quiet=True)).run_dir
    assert not (run / "system_prompt.txt").exists()
    calls = (run / "llm_calls.jsonl").read_text()
    assert "Lighthouse" not in calls and "chars" in calls and "reply" not in calls
    assert "secret plans" not in json.dumps(read_spans(run)[0]["attributes"])


def test_the_a2a_task_is_recorded_on_the_trace(workspace):
    import httpx
    from app.a2a_server import create_app
    app = create_app("http://localhost:8000", offline=True)

    async def go():
        body = {"jsonrpc": "2.0", "id": 1, "method": "SendMessage", "params": {"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"text": "Brief me"}]}}}
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8000", timeout=60) as c:
            return (await c.post("/", json=body, headers={"Content-Type": "application/json", "A2A-Version": "1.0"})).json()["result"]["task"]
    task = asyncio.run(go())
    m = json.loads((only_run() / "run.json").read_text())
    assert m["entry"]["type"] == "a2a" and m["entry"]["task_id"] == task["id"] and m["entry"]["context_id"] == task["contextId"]
    assert read_spans(only_run())[0]["attributes"]["a2a.task_id"] == task["id"]


def test_spans_can_be_sent_to_an_otlp_backend(workspace, monkeypatch):
    received = []

    class Receiver(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append((self.path, self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *a):
            pass
    server = HTTPServer(("127.0.0.1", 0), Receiver)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", f"http://127.0.0.1:{server.server_port}")
    asyncio.run(run_once("brief me", offline=True, quiet=True))
    server.shutdown()
    assert received and received[0][0] == "/v1/traces"
    payload = b"".join(body for _, body in received)
    assert b"invoke_agent" in payload and b"execute_tool" in payload and b"gen_ai.tool.name" in payload


def test_runs_cli_list_show_export_prune(workspace, capsys):
    for goal in ("one", "two", "three"):
        asyncio.run(run_once(goal, offline=True, quiet=True))
    capsys.readouterr()
    runs_cli([])
    out = capsys.readouterr().out
    assert out.count("completed") == 3 and "three" in out
    runs_cli(["show", "latest"])
    shown = capsys.readouterr().out
    assert "invoke_agent" in shown and "execute_tool write_file" in shown and "guardrail.blocked" in shown
    runs_cli(["export", "latest"])
    zips = list(runs_dir().glob("*.zip"))
    assert len(zips) == 1
    names = zipfile.ZipFile(zips[0]).namelist()
    assert any(n.endswith("run.json") for n in names) and any(n.endswith("trace.html") for n in names) and not any("/workspace/" in n for n in names)
    runs_cli(["prune", "--keep", "1"])
    assert len([p for p in runs_dir().iterdir() if (p / "run.json").exists()]) == 1
