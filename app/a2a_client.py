"""MODULE 11 · A2A CLIENT – the smallest possible "call an agent by its URL" program.

    python -m app.a2a_client "Brief me on the workspace" --url http://localhost:8000

It is also the reference for YOUR code: any program that can send HTTP can do what this file does.
(Plain `curl` examples are in README.md.)  Steps: 1) read the Agent Card  2) send a message  3) watch the task
move through working → (input-required) → completed  4) read the answer and the artifacts (files) it produced.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
import uuid

import httpx
from a2a.client import ClientConfig, create_client
from a2a.helpers import get_message_text
from a2a.types import Message, Part, Role, SendMessageRequest, TaskState

DONE = {TaskState.TASK_STATE_COMPLETED, TaskState.TASK_STATE_FAILED, TaskState.TASK_STATE_CANCELED, TaskState.TASK_STATE_REJECTED}


def user_message(text: str, task_id: str = "", context_id: str = "") -> SendMessageRequest:
    return SendMessageRequest(message=Message(message_id=str(uuid.uuid4()), role=Role.ROLE_USER, parts=[Part(text=text)],
                                              task_id=task_id, context_id=context_id))


async def ask_agent(url: str, goal: str, *, token: str = "", approve=None, on_step=lambda text: None,
                    http: httpx.AsyncClient | None = None) -> dict:
    """Send `goal` to the agent at `url`; return {"state", "answer", "artifacts": {name: text}, "task_id"}.
    `approve(question) -> bool` is called when the agent needs a human decision (default: say no)."""
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    async with (http or httpx.AsyncClient(headers=headers, timeout=600)) as http:
        client = await create_client(url, ClientConfig(httpx_client=http))
        request, task_id, context_id = user_message(goal), "", ""
        while True:
            state, answer, artifacts, question = None, "", {}, None
            async for event in client.send_message(request):
                kind = event.WhichOneof("payload")
                if kind == "task":
                    task_id, context_id = event.task.id, event.task.context_id
                    state, answer = event.task.status.state, get_message_text(event.task.status.message)
                    for a in event.task.artifacts:
                        artifacts[a.name] = "\n".join(p.text for p in a.parts if p.text) or json.dumps(
                            [dict(p.data) if hasattr(p.data, "keys") else str(p.data) for p in a.parts if p.HasField("data")])
                elif kind == "status_update":
                    task_id, context_id = event.status_update.task_id, event.status_update.context_id
                    state, text = event.status_update.status.state, get_message_text(event.status_update.status.message)
                    on_step(text)
                    answer = text or answer
                    if state == TaskState.TASK_STATE_INPUT_REQUIRED:
                        question = text
                elif kind == "artifact_update":
                    a = event.artifact_update.artifact
                    artifacts[a.name] = "\n".join(p.text for p in a.parts if p.text) or "(structured data)"
            if state == TaskState.TASK_STATE_INPUT_REQUIRED and question:           # a human decision is needed
                ok = approve(question) if approve else False
                request = user_message("approve" if ok else "deny", task_id, context_id)
                continue
            return {"state": TaskState.Name(state) if state is not None else "UNKNOWN", "answer": answer,
                    "artifacts": artifacts, "task_id": task_id}


def main() -> int:
    p = argparse.ArgumentParser(description="Call an A2A agent by URL.")
    p.add_argument("goal")
    p.add_argument("--url", default="http://localhost:8000")
    p.add_argument("--token", default="", help="bearer token, if the server needs one (A2A_TOKEN)")
    p.add_argument("--yes", action="store_true", help="approve every approval request")
    args = p.parse_args()

    def approve(question: str) -> bool:
        print(f"\n  ⚠ {question}")
        return args.yes or (sys.stdin.isatty() and input("  Allow? [y/N] ").strip().lower() in ("y", "yes"))

    result = asyncio.run(ask_agent(args.url, args.goal, token=args.token, approve=approve, on_step=lambda t: print(" ", t[:160])))
    print(f"\nSTATE: {result['state']}\nANSWER: {result['answer']}\nARTIFACTS: {', '.join(result['artifacts']) or 'none'}")
    return 0 if result["state"] == "TASK_STATE_COMPLETED" else 1


if __name__ == "__main__":
    sys.exit(main())
