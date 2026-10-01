"""Live smoke test against the real model. Opt-in:  RUN_LIVE_TESTS=1 python -m pytest tests/test_live.py
(For a friendlier check use:  python -m app doctor --live)"""
import os

import pytest

from app.config import load_settings

pytestmark = pytest.mark.skipif(not (os.environ.get("RUN_LIVE_TESTS") and load_settings().api_key),
                                reason="live tests are opt-in: set RUN_LIVE_TESTS=1 and a real key in .env")


def test_model_can_call_a_tool():
    from app.llm_client import LLM
    tools = [{"type": "function", "function": {"name": "get_number", "description": "Returns the secret number.",
                                                "parameters": {"type": "object", "properties": {}}}}]
    turn = LLM(load_settings()).complete([{"role": "user", "content": "Call get_number to find the secret number."}], tools)
    assert turn.tool_calls and turn.tool_calls[0].name == "get_number"
