"""MODULE 11 · A2A SERVER – lets other programs (and the web page) call your agent at a URL.

A2A ("Agent2Agent") is an open standard for ONE agent to call ANOTHER agent over HTTP, whatever language or
framework each is built with. Two things make it work:

  1. AGENT CARD  – a "business card" at  /.well-known/agent-card.json  (name, what it can do, how to call it)
  2. JSON-RPC    – you POST a message to the agent's URL; the agent answers with a TASK
                   (state: working → completed / failed, plus ARTIFACTS = the files it produced)

We use the official `a2a-sdk` for the protocol. This file only adds what is specific to OUR agent:
  • the Agent Card, built from agent.toml
  • an "executor" that turns an incoming message into a call to runner.run_once()
  • live progress: every agent step is streamed as a status update (the web page shows them as they happen)
  • human approval: a risky tool call makes the task go to  input-required;  the caller answers "approve" / "deny"

Both protocol versions are served on the same URL: A2A 1.0 (SendMessage …) and 0.3 (message/send …).
"""
from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path

from a2a.helpers import (get_message_text, new_data_artifact, new_task_from_user_message, new_text_artifact,
                         new_text_message)
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events import EventQueue
from a2a.server.request_handlers import DefaultRequestHandler
from a2a.server.request_handlers.response_helpers import agent_card_to_dict
from a2a.server.routes import create_jsonrpc_routes
from a2a.server.tasks import InMemoryTaskStore, TaskUpdater
from a2a.types import AgentCapabilities, AgentCard, AgentInterface, AgentSkill, Part, TaskState
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse, PlainTextResponse
from starlette.routing import Route

from app.config import load_profile
from app.runner import RunOutcome, run_once

UI_FILE = Path(__file__).parent / "ui" / "index.html"
MAX_CONCURRENT_RUNS = 2            # the free model tier is rate limited: extra requests wait their turn
MAX_ARTIFACT_CHARS = 200_000
APPROVE_WORDS = ("approve", "approved", "yes", "y", "ok", "allow", "go ahead")


# ───────────────────────────── the Agent Card ─────────────────────────────
def build_card(base_url: str) -> AgentCard:
    profile = load_profile()
    agent = profile["agent"]
    skills = profile["a2a_skills"] or [{"id": "run-goal", "name": "Work on a goal", "description": agent["description"]}]
    return AgentCard(
        name=agent["name"], description=agent["description"], version=agent["version"],
        supported_interfaces=[AgentInterface(url=base_url.rstrip("/") + "/", protocol_binding="JSONRPC", protocol_version="1.0")],
        capabilities=AgentCapabilities(streaming=True, push_notifications=False),
        default_input_modes=["text/plain"], default_output_modes=["text/plain", "text/markdown", "application/json"],
        skills=[AgentSkill(id=s["id"], name=s["name"], description=s["description"], tags=s.get("tags", []),
                           examples=s.get("examples", [])) for s in skills])


# ───────────────────────────── one running agent per task ─────────────────────────────
@dataclass
class RunHandle:
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)     # items: ("event", dict) | ("approval", (tool, args)) | ("done", outcome) | ("error", text)
    task: asyncio.Task | None = None
    pending: asyncio.Future | None = None                           # set while waiting for a human's approve/deny


def step_text(event: dict) -> str:
    kind = event["kind"]
    if kind == "act":
        return f'ACT {event["tool"]} {str(event.get("args", {}))[:200]}'
    detail = event.get("summary") or event.get("text") or event.get("reason") or ""
    return f"{kind.upper()} {detail}"[:400]


class AgentRunExecutor(AgentExecutor):
    def __init__(self, offline: bool, auto_approve: bool, in_place: bool):
        self.offline, self.auto_approve, self.in_place = offline, auto_approve, in_place
        self.runs: dict[str, RunHandle] = {}
        self.slots = asyncio.Semaphore(MAX_CONCURRENT_RUNS)

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        if context.current_task is None:                      # first message of a new task
            await event_queue.enqueue_event(new_task_from_user_message(context.message))
        updater = TaskUpdater(event_queue, context.task_id, context.context_id)
        handle = self.runs.get(context.task_id)
        reply = get_message_text(context.message).strip()

        if handle and handle.pending and not handle.pending.done():      # the human answered an approval question
            handle.pending.set_result(reply.lower().split(" ")[0] in APPROVE_WORDS or reply.lower() in APPROVE_WORDS)
            await updater.start_work(new_text_message("Thank you – continuing." if handle.pending.result() else "Understood – that action is denied."))
        elif handle is None:                                  # a brand-new run
            if not reply:
                await updater.reject(new_text_message("Please send a goal as text."))
                return
            await updater.start_work(new_text_message("Starting."))
            handle = self.runs[context.task_id] = RunHandle()
            handle.task = asyncio.create_task(self._run(handle, reply, {"type": "a2a", "task_id": context.task_id, "context_id": context.context_id}))
        else:
            # A message arrived while the agent is mid-run and not waiting for an answer: ignore it politely.
            await updater.update_status(TaskState.TASK_STATE_WORKING, new_text_message("Still working on the current goal – message ignored."))
            return

        try:
            await self._drive(handle, context, updater)
        except asyncio.CancelledError:
            if handle.task and not handle.task.done():
                handle.task.cancel()
            raise

    async def _run(self, handle: RunHandle, goal: str, origin: dict) -> None:
        async def approve(tool: str, args: dict) -> bool:
            if self.auto_approve:
                return True
            handle.pending = asyncio.get_running_loop().create_future()
            handle.queue.put_nowait(("approval", (tool, args)))
            return await handle.pending
        try:
            async with self.slots:
                outcome = await run_once(goal, offline=self.offline, in_place=self.in_place, quiet=True, approve=approve, origin=origin,
                                         sink=lambda ev: handle.queue.put_nowait(("event", ev)))
            handle.queue.put_nowait(("done", outcome))
        except asyncio.CancelledError:
            raise
        except BaseException as exc:                          # SystemExit (e.g. missing API key) included
            handle.queue.put_nowait(("error", f"{type(exc).__name__}: {exc}"))

    async def _drive(self, handle: RunHandle, context: RequestContext, updater: TaskUpdater) -> None:
        """Forward the run's progress to the caller until it finishes or needs a human decision."""
        while True:
            kind, payload = await handle.queue.get()
            if kind == "event":
                await updater.update_status(TaskState.TASK_STATE_WORKING, new_text_message(step_text(payload)))
            elif kind == "approval":
                tool, args = payload
                await updater.requires_input(new_text_message(
                    f"APPROVAL NEEDED: the agent wants to run `{tool}` with {args}. Reply 'approve' or 'deny'."))
                return                                        # task waits; the next message resumes it (see top of execute)
            elif kind == "done":
                self.runs.pop(context.task_id, None)
                await self._publish_results(updater, payload)
                return
            elif kind == "error":
                self.runs.pop(context.task_id, None)
                await updater.failed(new_text_message(payload))
                return

    @staticmethod
    async def _publish_results(updater: TaskUpdater, o: RunOutcome) -> None:
        parts = [("report.md", o.report_path), ("changes.diff", o.run_dir / "changes.diff")] + [(p.relative_to(o.run_dir).as_posix(), p) for p in o.outputs]
        for name, path in parts:
            if path.exists() and path.stat().st_size <= MAX_ARTIFACT_CHARS:
                art = new_text_artifact(name, path.read_text(encoding="utf-8", errors="replace"),
                                        media_type="text/markdown" if name.endswith(".md") else "text/plain")
                await updater.add_artifact(list(art.parts), artifact_id=art.artifact_id, name=name)
        art = new_data_artifact("result.json", {**_read_json(o.result_path)}, media_type="application/json")
        await updater.add_artifact(list(art.parts), artifact_id=art.artifact_id, name="result.json")
        message = new_text_message(o.answer or "(no answer)")
        message.metadata.update({"agentStatus": o.status, "runId": o.run_dir.name})
        await (updater.complete(message) if o.status == "completed" else updater.failed(message))

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        handle = self.runs.pop(context.task_id, None)
        if handle and handle.task:
            handle.task.cancel()
        await TaskUpdater(event_queue, context.task_id, context.context_id).cancel(new_text_message("Cancelled."))


def _read_json(path: Path) -> dict:
    import json
    return json.loads(path.read_text(encoding="utf-8"))


# ───────────────────────────── the web app ─────────────────────────────
class LocalOnlyGuard:
    """Protect a server on your own computer from web pages in your browser that try to call it behind your back
    (CSRF / DNS-rebinding), and optionally require a password token (A2A_TOKEN) for everyone else."""

    def __init__(self, app, allowed_hosts: set[str], token: str):
        self.app, self.allowed_hosts, self.token = app, allowed_hosts, token

    async def __call__(self, scope, receive, send):
        if scope["type"] == "http":
            headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
            host = headers.get("host", "").rsplit(":", 1)[0].strip("[]")
            problem = None
            if self.allowed_hosts and host not in self.allowed_hosts:
                problem = (403, f"Host '{host}' is not allowed. Set PUBLIC_HOSTS to allow it.")
            elif scope["method"] == "POST" and not headers.get("content-type", "").startswith("application/json"):
                problem = (415, "POST requests must use Content-Type: application/json.")
            elif self.token and scope["method"] == "POST" and headers.get("authorization") != f"Bearer {self.token}":
                problem = (401, "Missing or wrong bearer token.")
            if problem:
                await JSONResponse({"error": problem[1]}, status_code=problem[0])(scope, receive, send)
                return
        await self.app(scope, receive, send)


def create_app(base_url: str, *, offline: bool = False, auto_approve: bool = False, in_place: bool = False) -> Starlette:
    card = build_card(base_url)
    handler = DefaultRequestHandler(agent_executor=AgentRunExecutor(offline, auto_approve, in_place),
                                    task_store=InMemoryTaskStore(), agent_card=card)

    async def ui(request: Request):
        return HTMLResponse(UI_FILE.read_text(encoding="utf-8"))

    async def health(request: Request):
        return PlainTextResponse("ok")

    # One "hybrid" Agent Card: A2A 1.0 fields + the A2A 0.3 fields (url, protocolVersion …) so BOTH kinds of client can read it.
    hybrid = {**agent_card_to_dict(card), "url": base_url.rstrip("/") + "/", "protocolVersion": "0.3.0", "preferredTransport": "JSONRPC"}

    async def card_endpoint(request: Request):
        return JSONResponse(hybrid)

    routes = [Route("/.well-known/agent-card.json", card_endpoint, methods=["GET"]),
              Route("/.well-known/agent.json", card_endpoint, methods=["GET"]),      # older clients look here
              *create_jsonrpc_routes(handler, "/", enable_v0_3_compat=True),         # POST /  (A2A 1.0 and 0.3)
              Route("/", ui, methods=["GET"]), Route("/health", health, methods=["GET"])]
    app = Starlette(routes=routes)
    host = base_url.split("//", 1)[-1].split("/")[0].rsplit(":", 1)[0]
    allowed = {"localhost", "127.0.0.1", "::1", host, *filter(None, os.environ.get("PUBLIC_HOSTS", "").split(","))}
    return LocalOnlyGuard(app, allowed if not os.environ.get("ALLOW_ANY_HOST") else set(), os.environ.get("A2A_TOKEN", ""))


def serve(host: str | None = None, port: int | None = None) -> None:
    import uvicorn
    profile = load_profile()["server"]
    host, port = host or profile["host"], port or int(profile["port"])
    base_url = os.environ.get("PUBLIC_URL") or f"http://{'localhost' if host in ('0.0.0.0', '127.0.0.1') else host}:{port}"
    offline, auto, in_place = (bool(os.environ.get(k)) for k in ("OFFLINE", "AUTO_APPROVE", "IN_PLACE"))
    if host not in ("127.0.0.1", "localhost") and not os.environ.get("A2A_TOKEN"):
        print("⚠ You are exposing the agent beyond this computer WITHOUT a password. Set A2A_TOKEN in .env first.")
    print(f"\nAgent '{load_profile()['agent']['name']}' is listening.\n"
          f"  Web page   : {base_url}/\n  Agent Card : {base_url}/.well-known/agent-card.json\n  A2A URL    : {base_url}/   (POST JSON-RPC)\n"
          f"  Model      : {'offline script' if offline else 'real model'} · human approval: {'OFF (--yes)' if auto else 'ON'}\n")
    uvicorn.run(create_app(base_url, offline=offline, auto_approve=auto, in_place=in_place), host=host, port=port, log_level="warning")
