import httpx
import openai
import pytest

from app.config import load_settings
from app.llm_client import LLM, LLMError, parse_response


class FakeResponse:
    """Mimics the SDK's response object just enough for parse_response."""
    def __init__(self, content=None, tool_calls=None):
        msg = type("M", (), {"content": content, "tool_calls": tool_calls, "reasoning_content": "thinking…"})()
        self.choices = [type("C", (), {"message": msg})()]


def make_tool_call(name, arguments, id="c1"):
    fn = type("F", (), {"name": name, "arguments": arguments})()
    return type("T", (), {"id": id, "function": fn})()


def llm(monkeypatch, create):
    monkeypatch.setenv("NVIDIA_API_KEY", "test-key")
    sleeps = []
    model = LLM(load_settings(), sleep=sleeps.append, clock=lambda: 0.0)
    model.client.chat.completions.create = create
    return model, sleeps


def rate_limit_error(retry_after=None):
    headers = {"retry-after": retry_after} if retry_after else {}
    response = httpx.Response(429, headers=headers, request=httpx.Request("POST", "http://x"))
    return openai.RateLimitError("slow down", response=response, body=None)


def test_parse_response_reads_tool_calls_and_bad_json():
    turn = parse_response(FakeResponse(None, [make_tool_call("read_file", '{"path": "a"}'), make_tool_call("x", "{oops")]))
    assert turn.tool_calls[0].args == {"path": "a"} and turn.reasoning == "thinking…"
    assert turn.tool_calls[1].bad_json == "{oops"


def test_rate_limit_is_retried_with_backoff(monkeypatch):
    attempts = []

    def create(**kw):
        attempts.append(1)
        if len(attempts) < 3:
            raise rate_limit_error()
        return FakeResponse("hello")
    model, sleeps = llm(monkeypatch, create)
    assert model.complete([{"role": "user", "content": "hi"}]).text == "hello"
    assert [s for s in sleeps if s >= 5] == [5.0, 10.0]          # 5s then 10s


def test_retry_after_header_is_respected(monkeypatch):
    calls = []

    def create(**kw):
        calls.append(1)
        if len(calls) == 1:
            raise rate_limit_error("7")
        return FakeResponse("ok")
    model, sleeps = llm(monkeypatch, create)
    model.complete([])
    assert 7.0 in sleeps


def test_bad_key_stops_immediately(monkeypatch):
    def create(**kw):
        raise openai.AuthenticationError("no", response=httpx.Response(401, request=httpx.Request("POST", "http://x")), body=None)
    model, _ = llm(monkeypatch, create)
    with pytest.raises(LLMError, match="API key"):
        model.complete([])


def test_forbidden_key_is_explained(monkeypatch):
    def create(**kw):
        raise openai.PermissionDeniedError("Authorization failed", response=httpx.Response(403, request=httpx.Request("POST", "http://x")), body=None)
    model, _ = llm(monkeypatch, create)
    with pytest.raises(LLMError, match="API key was rejected"):
        model.complete([])


def test_missing_key_message(monkeypatch):
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)
    for name in ("LLM_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(SystemExit, match="No API key"):
        LLM(load_settings().__class__(**{**load_settings().__dict__, "api_key": ""}))
