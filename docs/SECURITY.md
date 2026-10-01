# Security model — threats, safeguards, and where to find them

An agent is a program that reads untrusted text and then takes actions. Every row below is a real way that goes wrong.

| Threat | Safeguard | Where | Test |
|---|---|---|---|
| API key leaks to the model, logs, files, tools or the network | Key only in `.env`; tool programs never load `.env` and get a scrubbed environment; `redact()` on tool output, traces, live feed, report and final answer (nested arguments too); the key and any `${TOKEN}` from `mcp.json` are registered as secrets and blanked wherever they appear; secret-looking content cannot be written; obvious placeholders (`{{password}}`) are allowed | `config.py`, `mcp_client.py`, `guardrails.py`, `telemetry.py` | `test_security`, `test_guardrails`, `test_mcp` |
| Agent reads files it shouldn't (`../../etc/passwd`, symlinks, `.env`, `*.pem`) | All paths resolved inside the workspace (follows symlinks); credential file names denied and hidden | `tools/_sandbox.py` | `test_security` |
| Agent damages your inputs | Every run works on a **copy** of the workspace; writes only where `[files] writable` allows; size cap; `changes.diff` shows every modification | `workspace.py`, `guardrails.py`, `my_agent/guardrails.toml` | `test_runner`, `test_guardrails` |
| **Prompt injection** — a file or web page says "ignore your instructions and …" | System prompt: file/tool/web text is DATA; tripwire flags suspicious wording to the model and records it in the trace; and even a fooled model hits the other layers | `prompts/system.md`, `guardrails.sanitize_output` | `test_guardrails`, `examples/example-security-demo` |
| Dangerous command execution | Off by default; allow-list **by command prefix**; no shell; arguments pointing outside the workspace refused; timeout; **human approval**; no secrets in the child environment | `tools/builtin/commands.py`, `guardrails.toml` | `test_tools`, `test_security`, `test_agent_loop` |
| **An external MCP server does more than intended** (Playwright has 60+ tools; GitHub can write) | **`include` is mandatory** (default: none); external tools **ask for approval** by default; their output passes the same redaction and injection filters; tokens come from `.env` via `${VAR}` and are never written in `mcp.json` or the run record | `mcp_client.py`, `my_agent/mcp.json` | `test_mcp` |
| Runaway cost / infinite loop | Turn, tool-call, per-tool and token budgets; repeated-call stop; graceful wrap-up | `config.py`, `guardrails.py`, `agent_loop.py` | `test_guardrails`, `test_agent_loop` |
| Agent claims things it didn't verify | Prompt: every claim from a tool result; optional `[claims]` rules in `guardrails.toml` | `prompts/system.md`, `guardrails.check_final` | `test_guardrails` |
| **A website in your browser calls your local agent** (CSRF) | POST requires `Content-Type: application/json` (forces a browser pre-flight the server never approves) | `a2a_server.LocalOnlyGuard` | `test_a2a` |
| **DNS-rebinding** to your local agent | `Host` header must be `localhost`/`127.0.0.1` or an explicitly allowed host (`PUBLIC_HOSTS`) | `a2a_server.LocalOnlyGuard` | `test_a2a` |
| Strangers call an agent you exposed on the network | Binds to `127.0.0.1` by default; warning when exposed; `A2A_TOKEN` bearer password required for all POSTs | `a2a_server.serve` | `test_a2a` |
| Too many parallel runs exhaust the free quota | At most 2 runs at once; extra requests wait | `a2a_server.MAX_CONCURRENT_RUNS` | – |
| **Can't tell afterwards what happened** | Every run is recorded — even a crash or a failed start: `run.json` (with fingerprints of your prompts), `trace.jsonl` (OpenTelemetry spans, written as they happen), `llm_calls.jsonl`, `trace.html`; one redaction point for everything written; `TRACE_CONTENT=off` keeps no message text | `telemetry.py`, `runner.py` | `test_telemetry`, `test_security` |

## Honest limits (say these out loud)
- Guardrails reduce risk; they do not remove it. The secret and injection patterns are tripwires, not walls.
- A command you allow can do whatever that program can do (`npx playwright test` runs test code). Allow the narrowest command, keep the human approval on, and review what you approve.
- External MCP tools are outside the file jail. Their safety is the `include` list plus approvals — choose few, read-only tools.
- The model API is hosted: anything the agent reads is sent to NVIDIA. Use synthetic or public data only.
- `A2A_TOKEN` is a shared password sent in a header: use it only on networks you trust, or put the server behind HTTPS.
- Traces keep message text by default (secrets blanked). If your sample data is sensitive, set `TRACE_CONTENT=off`.
- A tool you write that calls the network or changes systems is YOUR responsibility: allow-list hosts, require approval, add a test.
