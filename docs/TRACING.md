# Tracing & logs — seeing what your agent did, and why

An agent decides things by itself, so you must be able to **replay its thinking**. Every single run (terminal, web page or A2A call)
leaves a complete record in its own folder under `runs/`. Nothing to switch on.

## What you get, for every run
```
runs/20261002-143015-ab12/
  trace.html          ← OPEN THIS. A picture of the run: timeline, conversation, numbers. Double-click; no server needed.
  report.md           the readable story: goal, status, tools used, why it stopped, final answer, every step
  result.json         the answer as data (+ your own JSON if the agent produced it)
  run.json            the "ticket": who/when/what model, settings, fingerprints of your prompts, totals, any error
  trace.jsonl         the spans (see below), written line by line while the run happens
  llm_calls.jsonl     every message sent to the model and every reply, with token counts and timings
  system_prompt.txt   the exact instructions the model received
  changes.diff        what the agent changed in your files (only if it edited something)
  output/             the files the agent produced
runs/index.html       a list of ALL runs (open it to compare runs)
```

## Reading `trace.html`
- **Top cards:** turns, model calls, tokens, tool calls (and errors), guardrail blocks, approvals, time spent in the model vs tools, time lost to rate limits.
- **Timeline:** one row per step — `chat` (the model thinking), `execute_tool` (a tool running). Bars show *when* and *how long*.
  Filter to **Guardrails & errors** to see only what went wrong or was stopped. Click a row for the arguments, the real result, and events like `guardrail.blocked` or `approval.denied`.
- **Conversation:** the whole dialogue — system prompt, goal, the model's replies (and its private thinking, if it gives it), tool results.
- **Manifest:** `run.json` — including *fingerprints* (short hashes) of `agent.md`, skills, `guardrails.toml`… If a run behaves differently from yesterday, compare fingerprints: *did the prompt change?*
- A bar with stripes = a step that **never finished** (the run was interrupted there).

## From the terminal
```bash
python -m app runs                    # list all runs, newest first
python -m app runs show latest        # the steps of one run as a tree, with durations and guardrail events
python -m app runs open latest        # open its picture in your browser   (python -m app runs open index  for all runs)
python -m app runs export latest      # runs/<id>.zip: an evidence bundle (secrets already blanked out)
python -m app runs prune --keep 20    # delete older runs
```
Handing in work? **`runs export`** gives judges real evidence: the trace, the tool outputs, the diff and the final answer.

## The promises (so you can trust it)
1. **Every run is recorded** — even one that fails to start (for example a missing key) gets a folder and a `failed` ticket.
2. **Crash-safe** — each step is written to disk the moment it happens. If the program is killed, the trace up to that moment is still there, and unfinished steps are shown as such. `run.json` always ends with a status: `completed`, `failed`, `crashed`, `cancelled`, `out_of_turns`, `out_of_budget`.
3. **Secrets never reach a log** — one filter at the single point where files are written blanks out keys and tokens (including the ones from `mcp.json`).
4. **Same for every front door** — the terminal, the web page and A2A all go through the same code, so the record is identical. For A2A the task id and context id are written into the trace.
5. **Standard format** — spans follow the OpenTelemetry *GenAI* conventions (`invoke_agent`, `chat`, `execute_tool`, `gen_ai.usage.input_tokens` …), so professional tools can read them.

## Privacy: keep the text, or not
By default `llm_calls.jsonl` keeps the text of messages (secrets blanked). If your sample data is sensitive, set in `.env`:
```
TRACE_CONTENT=off
```
Then only sizes, timings, tool names and verdicts are kept — not the words.

## Optional: send traces to a dashboard (Phoenix, Langfuse, Jaeger…)
The local files are enough for the workshop. If you want a live dashboard, point the same spans at any OpenTelemetry (OTLP) endpoint:
```bash
# Jaeger (one command; UI at http://localhost:16686)
docker run --rm -p 16686:16686 -p 4318:4318 jaegertracing/all-in-one
# then in .env:
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
```
Arize Phoenix and Langfuse also accept OTLP — use the endpoint from their docs. The local files are still written.

## What the span names mean
| Span | Meaning |
|---|---|
| `invoke_agent <name>` | the whole run (the root) |
| `chat <model>` | one call to the model: latency, tokens in/out, retries and rate-limit waiting, which tools it asked for |
| `execute_tool <name>` | one tool call: arguments, result size and preview, `agent.guardrail.verdict` (allowed / blocked), `agent.approval` (not_required / approved / denied), duration, which server provided it |
