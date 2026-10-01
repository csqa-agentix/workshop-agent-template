# 🔵 app/ — the engine (you do not edit this)

This folder is the machinery that runs *any* agent folder. It knows nothing about your problem, on purpose.
You can read it to learn how an agent works — start with `agent_loop.py` (one short file).

| File | What it does |
|---|---|
| `__main__.py` | the `python -m app …` commands |
| `agent_loop.py` | **the loop**: ask the model → run its tools → show it the results → repeat |
| `llm_client.py` | talks to the model (OpenAI SDK), waits and retries when rate-limited |
| `mcp_client.py`, `mcp_server.py` | the tool "plug" (MCP): built-in tools + external servers |
| `guardrails.py` | enforces the rules from `my_agent/guardrails.toml`, redacts secrets, flags hidden instructions |
| `telemetry.py`, `trace.py`, `runs_cli.py` | tracing: spans, run ticket, viewer pages, the `runs` command |
| `runner.py`, `workspace.py` | "do one complete run" on a safe copy of the files |
| `a2a_server.py`, `a2a_client.py` | call the agent by URL (A2A) |
| `doctor.py` | the "is my setup OK?" checker |
| `prompts/` | the general rules every agent gets (`system.md`) and the prompt loader |
| `tools/` | the built-in tools |
| `ui/` | the web page and the trace viewer pages |
