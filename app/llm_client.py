"""MODULE 3 · MODEL CLIENT – the only file that talks to the language model.

We use the official OpenAI SDK. NVIDIA's API speaks the same "chat completions" language,
so the only change is `base_url`. Swap the model or provider by editing .env, nothing else.

This file also protects us from the free tier's rate limit (about 40 requests/minute):
  1. a small pause between requests  (throttle)
  2. on HTTP 429 / 5xx / network trouble: wait (Retry-After or 5s, 10s, 20s …) and try again
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field

import openai
from openai import OpenAI

from app.config import Settings
from app.guardrails import register_secret


class LLMError(Exception):
    """A model problem we cannot fix by waiting (wrong key, wrong model name …)."""


@dataclass
class ToolCall:
    id: str
    name: str
    args: dict
    bad_json: str | None = None      # set when the model sent arguments that are not valid JSON


@dataclass
class Turn:
    """One answer from the model: some text and/or some tool calls."""
    text: str = ""
    tool_calls: list[ToolCall] = field(default_factory=list)
    reasoning: str = ""              # private "thinking", if the model returns it
    tokens: int = 0                  # tokens this request used (for the budget)
    meta: dict = field(default_factory=dict)    # model, latency, retries, token split … (for tracing)

    def to_message(self) -> dict:
        """The assistant message we append to the conversation."""
        msg: dict = {"role": "assistant", "content": self.text or ""}
        if self.tool_calls:
            msg["tool_calls"] = [
                {"id": c.id, "type": "function",
                 "function": {"name": c.name, "arguments": c.bad_json or json.dumps(c.args)}}
                for c in self.tool_calls]
        return msg


def _thinking_options(mode: str) -> dict:
    if mode == "off":
        return {"chat_template_kwargs": {"enable_thinking": False}}
    if mode == "on":
        return {"chat_template_kwargs": {"enable_thinking": True}}
    return {"chat_template_kwargs": {"enable_thinking": True, "low_effort": True}}   # "low": faster steps


def parse_response(response) -> Turn:
    """Turn the SDK's response object into our small Turn object."""
    msg = response.choices[0].message
    calls = []
    for i, c in enumerate(msg.tool_calls or []):
        raw = c.function.arguments or "{}"
        try:
            args, bad = json.loads(raw), None
        except json.JSONDecodeError:
            args, bad = {}, raw
        calls.append(ToolCall(c.id or f"call_{i}", c.function.name, args if isinstance(args, dict) else {}, bad))
    reasoning = getattr(msg, "reasoning_content", None) or getattr(msg, "reasoning", None) or ""
    usage = getattr(response, "usage", None)
    tokens = getattr(usage, "total_tokens", 0) or 0
    meta = {"input_tokens": getattr(usage, "prompt_tokens", 0) or 0, "output_tokens": getattr(usage, "completion_tokens", 0) or 0,
            "finish_reason": getattr(response.choices[0], "finish_reason", None), "response_model": getattr(response, "model", None)}
    return Turn(text=(msg.content or "").strip(), tool_calls=calls, reasoning=reasoning.strip(), tokens=tokens, meta=meta)


class LLM:
    def __init__(self, settings: Settings, sleep=time.sleep, clock=time.monotonic):
        if not settings.api_key:
            raise SystemExit("No API key found. Copy .env.example to .env and paste your NVIDIA key after NVIDIA_API_KEY= "
                             "(or run with --offline to try the agent without a model).")
        self.s = settings
        register_secret(settings.api_key)            # the key is blanked out of every log, report and answer
        # max_retries=0: WE handle retries below so that we can explain what is happening.
        self.client = OpenAI(api_key=settings.api_key, base_url=settings.base_url,
                             max_retries=0, timeout=settings.timeout_seconds)
        self.sleep, self.clock, self._last_call = sleep, clock, 0.0

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> Turn:
        """Ask the model for its next move. `tools=None` forces a plain text answer."""
        request: dict = dict(model=self.s.model, messages=messages, temperature=self.s.temperature,
                             top_p=self.s.top_p, max_tokens=self.s.max_tokens,
                             extra_body=_thinking_options(self.s.thinking))
        if tools:
            request.update(tools=tools, tool_choice="auto")
        waited = 0.0
        for attempt in range(self.s.max_retries + 1):
            self._throttle()
            started = time.monotonic()
            try:
                response = self.client.chat.completions.create(**request)
                turn = parse_response(response)
                turn.meta.update(model=self.s.model, latency_s=round(time.monotonic() - started, 3), attempts=attempt + 1,
                                 rate_limit_wait_s=round(waited, 1), temperature=self.s.temperature, top_p=self.s.top_p,
                                 max_tokens=self.s.max_tokens, provider="nvidia" if "nvidia" in self.s.base_url else "openai-compatible")
                return turn
            except (openai.RateLimitError, openai.InternalServerError,
                    openai.APIConnectionError, openai.APITimeoutError) as exc:
                if attempt == self.s.max_retries:
                    raise LLMError(f"Model still failing after {self.s.max_retries} retries: {exc}") from exc
                wait = self._wait_time(exc, attempt)
                print(f"  [model] {type(exc).__name__} – waiting {wait:.0f}s, then retry {attempt + 1}/{self.s.max_retries}")
                waited += wait
                self.sleep(wait)
            except (openai.AuthenticationError, openai.PermissionDeniedError) as exc:
                raise LLMError("The API key was rejected (wrong, expired, or no access to this model). Check NVIDIA_API_KEY in .env.") from exc
            except openai.NotFoundError as exc:
                raise LLMError(f"Model or URL not found – check MODEL and BASE_URL in .env. ({exc})") from exc
            except openai.BadRequestError as exc:
                raise LLMError(f"The model rejected the request: {exc}") from exc
        raise LLMError("unreachable")

    def _throttle(self) -> None:
        wait = self._last_call + self.s.min_seconds_between_calls - self.clock()
        if wait > 0:
            self.sleep(wait)
        self._last_call = self.clock()

    @staticmethod
    def _wait_time(exc, attempt: int) -> float:
        headers = getattr(getattr(exc, "response", None), "headers", None) or {}
        retry_after = headers.get("retry-after")
        if retry_after and retry_after.replace(".", "", 1).isdigit():
            return min(float(retry_after), 60.0)
        return min(5.0 * 2 ** attempt, 60.0)          # 5s, 10s, 20s, 40s, 60s …


class ScriptedLLM:
    """OFFLINE stand-in for the model: replays a JSON script. The tools, MCP and guardrails stay real.
    Handy when the Wi-Fi is bad or the rate limit is hit. Script format: see examples/*/offline_script.json"""

    def __init__(self, script: list[dict]):
        self.script, self.i = script, 0

    def complete(self, messages: list[dict], tools: list[dict] | None = None) -> Turn:
        if self.i >= len(self.script):
            return Turn(text="(offline script finished)")
        step = self.script[self.i]
        self.i += 1
        calls = [ToolCall(f"call_{self.i}_{j}", c["tool"], c.get("args", {})) for j, c in enumerate(step.get("calls", []))]
        return Turn(text=step.get("say", ""), tool_calls=calls, meta={"model": "offline-script", "provider": "offline", "attempts": 1})
