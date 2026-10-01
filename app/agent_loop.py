"""MODULE 4 · THE AGENT LOOP – the heart of the repo. Read this file first.

    GOAL → model thinks → model asks for tools → we run them → results go back → model thinks again → … → final answer

The loop has NO business logic. It does not know what a "report", a "test" or a "ticket" is, and it never
decides the order of work – the MODEL decides, guided by the prompt (prompts/agent.md).
The loop only repeats these steps:

    1. ask the model what to do next          (llm.complete)
    2. if it asks for NO tools → that is its final answer → stop
    3. otherwise: guardrails check each tool call, a human approves risky ones
    4. run the allowed tools (all at once if the model asked for several)
    5. clean the results (no secrets, flag hidden instructions), put them in the conversation, go to 1
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Awaitable, Callable

from app.guardrails import INJECTION_BANNER, Guardrails, redact
from app.mcp_client import ToolHub
from app.telemetry import NullTelemetry
from app.trace import Trace, short

INJECTION_MARK = INJECTION_BANNER[:20]
TIMES_UP = ("You have run out of {what}. Do NOT call any more tools. Write your final answer now: "
            "what you did, what you found, and what a human still needs to do.")


@dataclass
class RunResult:
    status: str          # "completed" | "out_of_turns" | "out_of_budget"
    answer: str
    turns: int
    tool_calls: int


async def run_agent(*, goal: str, system_prompt: str, llm, hub: ToolHub, guard: Guardrails, trace: Trace,
                    max_turns: int, approve: Callable[[str, dict], Awaitable[bool]] | None = None, tele=None) -> RunResult:
    async def deny(tool: str, args: dict) -> bool:
        return False
    approve = approve or deny                                # no human available = risky actions are refused
    tele = tele or NullTelemetry()                           # the recorder: spans, model calls, timings (see telemetry.py)
    approval_lock = asyncio.Lock()                           # ask the human one question at a time
    messages = [{"role": "system", "content": system_prompt},
                {"role": "user", "content": f"GOAL:\n{goal}"}]
    tools = hub.openai_tools()
    tool_calls_made, turn, logged = 0, 0, 1          # logged = 1: the system prompt is saved once, not repeated per call

    async def run_one(call) -> dict:
        """Guardrails first, then (maybe) a human, then the real tool. Always return a tool message for the model."""
        trace.log("act", turn, tool=call.name, args=call.args)
        span = tele.start_tool(turn, call.name, call.args, call.id, hub.server_of(call.name))
        verdict, approval = "allowed", "not_required"
        if call.bad_json is not None:
            verdict = "bad_arguments"
            result = f"ERROR: your arguments were not valid JSON: {short(call.bad_json, 120)}. Call the tool again with valid JSON."
        elif (refusal := guard.check_before(call.name, call.args)):
            verdict = "blocked"
            trace.log("guard", turn, reason=refusal)
            tele.event(span, "guardrail.blocked", reason=refusal)
            result = refusal
        else:
            allowed = True
            if guard.needs_approval(call.name) or hub.needs_approval(call.name):
                tele.event(span, "approval.requested")
                async with approval_lock:
                    allowed = await approve(call.name, call.args)
                approval = "approved" if allowed else "denied"
                tele.event(span, f"approval.{approval}")
                if not allowed:
                    result = "DENIED: the human did not approve this action. Do not retry it; choose another way or report it."
                    trace.log("guard", turn, reason=f"human denied {call.name}")
            if allowed:
                result = guard.sanitize_output(await hub.call(call.name, call.args))
                if result.startswith(INJECTION_MARK):
                    tele.event(span, "guardrail.injection_flagged")
        trace.log("observe", turn, tool=call.name, summary=short(result, 160))
        tele.end_tool(span, result, verdict, approval, error=result.startswith(("ERROR", "DENIED")))
        return {"role": "tool", "tool_call_id": call.id, "content": result}

    async def ask_model(use_tools, wrap_up=False):
        """One model call, recorded as a span; returns the reply."""
        nonlocal logged
        span = tele.start_chat(turn, len(messages))
        fresh, logged = messages[logged:], len(messages)
        try:
            reply = await asyncio.to_thread(llm.complete, messages, tools if use_tools else None)
        except BaseException as exc:
            tele.end_chat(span, None, fresh, error=exc, wrap_up=wrap_up)
            raise
        tele.end_chat(span, reply, fresh, wrap_up=wrap_up)
        return reply

    status = "out_of_turns"
    for turn in range(1, max_turns + 1):
        if guard.out_of_tokens:
            status = "out_of_budget"
            break
        if guard.out_of_context(messages):
            status = "out_of_context"
            break
        # 1) the model decides (blocking network call → run it off the event loop)
        reply = await ask_model(use_tools=True)
        guard.add_tokens(getattr(reply, "tokens", 0))
        messages.append(reply.to_message())
        if reply.tool_calls and (reply.text or reply.reasoning):
            trace.log("think", turn, text=reply.text, **({"model_reasoning": reply.reasoning} if reply.reasoning else {}))

        # 2) no tool calls = the model believes it is done
        if not reply.tool_calls:
            objection = guard.check_final(reply.text, tool_calls_made)
            if objection is None:
                answer = redact(reply.text)
                trace.log("final", turn, text=answer)
                return RunResult("completed", answer, turn, tool_calls_made)
            trace.log("guard", turn, reason=objection)
            messages.append({"role": "user", "content": objection})
            continue

        # 3-5) run the tools (concurrently), feed all results back
        tool_calls_made += len(reply.tool_calls)
        messages.extend(await asyncio.gather(*(run_one(c) for c in reply.tool_calls)))
    else:
        turn = max_turns

    # Out of turns, budget or room: ask once, without tools, for a summary – a graceful ending instead of a crash.
    what = {"out_of_budget": "tokens", "out_of_context": "room in the conversation"}.get(status, "turns")
    trace.log("note", turn, text=f"out of {what} – asking the model to wrap up")
    messages.append({"role": "user", "content": TIMES_UP.format(what=what)})
    wrap_up = await ask_model(use_tools=False, wrap_up=True)
    answer = redact(wrap_up.text)
    trace.log("final", turn, text=answer)
    return RunResult(status, answer, turn, tool_calls_made)
