"""MODULE 9 · TRACING (the record) – a complete, crash-safe record of every run.

An autonomous agent decides things by itself, so you must be able to SEE what it did and why. For every run we write:

    runs/<id>/run.json          the "ticket": who/what/when, model, settings, fingerprints of your prompts, totals, errors
    runs/<id>/trace.jsonl       the SPANS: invoke_agent → chat (model call) / execute_tool (tool call), with timings
    runs/<id>/llm_calls.jsonl   every model request + reply (secrets blanked out; switch off with TRACE_CONTENT=off)
    runs/<id>/system_prompt.txt the exact instructions the model received
    runs/<id>/trace.html        a picture of the run – double-click to open, no server needed
    runs/index.html             a list of all runs

It follows the OpenTelemetry "GenAI" naming (invoke_agent / chat / execute_tool, gen_ai.* attributes) – the industry
standard – so the same spans can be sent to Phoenix, Langfuse, Jaeger… by setting OTEL_EXPORTER_OTLP_ENDPOINT.

Guarantees:  the run folder is created FIRST · every span/event is written (and flushed) the moment it happens, so a
crash or Ctrl-C still leaves a readable trace · run.json always ends with a status (completed / failed / crashed …)
· everything passes through redact() on its way to disk, so secrets never land in a log.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
import time
import traceback
from datetime import datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanProcessor, TracerProvider
from opentelemetry.trace import Status, StatusCode, set_span_in_context

from app.config import ROOT, agent_dir
from app.guardrails import redact

UI_DIR = Path(__file__).parent / "ui"
MAX_FIELD = 20_000             # longest single text we keep in a log line


def _safe(value):
    """Make a value safe for a log: redact secrets, cut very long text, make it OTel-attribute friendly."""
    if isinstance(value, str):
        value = redact(value)
        return value if len(value) <= MAX_FIELD else value[:MAX_FIELD] + f"… [{len(value) - MAX_FIELD} more characters]"
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return _safe(json.dumps(value, ensure_ascii=False, default=str))


def runs_dir() -> Path:
    return Path(os.environ.get("RUNS_DIR") or ROOT / "runs")


def atomic_write(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


# ───────────────────────────── span writer (append-only, flushed per line) ─────────────────────────────
class JsonlProcessor(SpanProcessor):
    def __init__(self, path: Path):
        self.path = path

    def write(self, record: dict) -> None:
        line = redact(json.dumps(record, ensure_ascii=False, default=str))      # one redaction point for the whole file
        with self.path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    @staticmethod
    def _ids(span) -> dict:
        ctx, parent = span.get_span_context(), span.parent
        return {"trace_id": f"{ctx.trace_id:032x}", "span_id": f"{ctx.span_id:016x}",
                "parent_id": f"{parent.span_id:016x}" if parent else None}

    def on_start(self, span, parent_context=None) -> None:
        self.write({"t": "start", **self._ids(span), "name": span.name, "start_ns": span.start_time,
                    "attributes": dict(span.attributes or {})})

    def on_end(self, span) -> None:
        self.write({"t": "end", **self._ids(span), "name": span.name, "start_ns": span.start_time, "end_ns": span.end_time,
                    "status": span.status.status_code.name, "status_description": span.status.description,
                    "attributes": dict(span.attributes or {}),
                    "events": [{"name": e.name, "time_ns": e.timestamp, "attributes": dict(e.attributes or {})} for e in span.events]})

    def shutdown(self) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return True


# ───────────────────────────── the recorder ─────────────────────────────
class NullTelemetry:
    """Does nothing. Used when no recording is wanted (some tests)."""
    def set_system_prompt(self, text): pass
    def set_tools(self, hub): pass
    def start_chat(self, turn, n_messages): return None
    def end_chat(self, span, reply, new_messages, error=None, wrap_up=False): pass
    def start_tool(self, turn, name, args, call_id, server): return None
    def end_tool(self, span, result, verdict, approval, error): pass
    def event(self, span, name, **attrs): pass
    def finish(self, status, **kw): pass


class RunTelemetry:
    def __init__(self, run_dir: Path, *, goal: str, origin: dict | None, settings, profile: dict, rules, offline: bool):
        self.run_dir, self.s, self.profile, self.rules, self.offline = run_dir, settings, profile, rules, offline
        self.capture = settings.trace_content
        self.started = time.time()
        self.name = profile["agent"]["name"]
        self.origin = origin or {"type": "cli"}
        self._t0: dict = {}                                   # when each open span started (kept out of the exported attributes)
        self.counters = dict(turns=0, llm_calls=0, input_tokens=0, output_tokens=0, llm_time_s=0.0, rate_limit_wait_s=0.0,
                             tool_calls=0, tool_errors=0, tool_time_s=0.0, guardrail_blocks=0, approvals_asked=0, approvals_denied=0)
        self.proc = JsonlProcessor(run_dir / "trace.jsonl")
        # OTEL_SERVICE_NAME is the standard way to name a service in a tracing backend; fall back to the agent's own name.
        service = os.environ.get("OTEL_SERVICE_NAME") or self.name
        self.provider = TracerProvider(resource=Resource.create({"service.name": service, "service.version": profile["agent"]["version"],
                                                                  "gen_ai.agent.name": self.name}))
        self.provider.add_span_processor(self.proc)
        self._add_otlp_exporter()
        self.tracer = self.provider.get_tracer("ai-agent", "1.0")
        conversation = self.origin.get("context_id") or run_dir.name
        self.root = self.tracer.start_span(f"invoke_agent {self.name}", attributes={
            "gen_ai.operation.name": "invoke_agent", "gen_ai.agent.name": self.name, "gen_ai.agent.version": profile["agent"]["version"],
            "gen_ai.conversation.id": conversation, "agent.run.id": run_dir.name, "agent.entry": self.origin.get("type", "cli"),
            **({"a2a.task_id": self.origin["task_id"]} if self.origin.get("task_id") else {}),
            **({"agent.goal": _safe(goal)} if self.capture else {})})
        self.ctx = set_span_in_context(self.root)
        self.manifest = {
            "run_id": run_dir.name, "trace_id": f"{self.root.get_span_context().trace_id:032x}",
            "started_at": datetime.fromtimestamp(self.started, timezone.utc).isoformat(timespec="seconds"),
            "ended_at": None, "duration_s": None, "status": "running", "stop_reason": None,
            "entry": self.origin, "agent": {"name": self.name, "version": profile["agent"]["version"], "folder": _rel(agent_dir()),
                                           "description": profile["agent"]["description"]},
            "goal": _safe(goal),
            "model": {"name": "offline-script" if offline else settings.model, "base_url": None if offline else settings.base_url,
                      "thinking": settings.thinking, "temperature": settings.temperature, "max_tokens": settings.max_tokens},
            "limits": {"max_turns": settings.max_turns, "max_tool_calls": rules.max_tool_calls, "max_total_tokens": rules.max_total_tokens,
                       "writable": list(rules.writable), "approval_required_for": list(rules.approval_tools),
                       "commands_allowed": list(rules.allowed_commands)},
            "fingerprints": fingerprints(), "tools": [], "mcp": [], "usage": {}, "answer": None, "outputs": [], "error": None,
            "environment": environment(), "trace_content_captured": self.capture,
        }
        self._write_manifest()

    # ── set-up helpers ───────────────────────────────────────────────────────────
    def _add_otlp_exporter(self) -> None:
        if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT") or os.environ.get("OTEL_EXPORTER_OTLP_TRACES_ENDPOINT"):
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
                from opentelemetry.sdk.trace.export import BatchSpanProcessor
                self.provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(timeout=5)))
            except Exception as exc:                                        # noqa: BLE001 – tracing must never break a run
                print(f"  [trace] could not start the OTLP exporter: {exc}")

    def set_system_prompt(self, text: str) -> None:
        self.manifest["fingerprints"]["system_prompt"] = hashlib.sha256(text.encode()).hexdigest()[:12]
        if self.capture:
            (self.run_dir / "system_prompt.txt").write_text(redact(text), encoding="utf-8")

    def set_tools(self, hub) -> None:
        self.manifest["tools"] = hub.names()
        self.manifest["mcp"] = hub.describe()

    # ── model calls ──────────────────────────────────────────────────────────────
    def start_chat(self, turn: int, n_messages: int):
        self.counters["turns"] = max(self.counters["turns"], turn)
        span = self.tracer.start_span(f"chat {self.manifest['model']['name']}", context=self.ctx, attributes={
            "gen_ai.operation.name": "chat", "gen_ai.request.model": self.manifest["model"]["name"], "agent.turn": turn,
            "agent.messages_in_context": n_messages})
        self._t0[span] = time.time()
        return span

    def end_chat(self, span, reply, new_messages: list, error: BaseException | None = None, wrap_up: bool = False) -> None:
        t0 = self._t0.pop(span, time.time())
        meta = (reply.meta if reply is not None else {}) or {}
        c = self.counters
        c["llm_calls"] += 1
        c["input_tokens"] += meta.get("input_tokens", 0)
        c["output_tokens"] += meta.get("output_tokens", 0)
        c["llm_time_s"] += meta.get("latency_s", time.time() - t0)
        c["rate_limit_wait_s"] += meta.get("rate_limit_wait_s", 0)
        attrs = {"gen_ai.provider.name": meta.get("provider", "?"), "gen_ai.response.model": meta.get("response_model") or "",
                 "gen_ai.response.finish_reasons": str(meta.get("finish_reason") or ""), "gen_ai.usage.input_tokens": meta.get("input_tokens", 0),
                 "gen_ai.usage.output_tokens": meta.get("output_tokens", 0), "gen_ai.request.temperature": meta.get("temperature", 0),
                 "gen_ai.request.max_tokens": meta.get("max_tokens", 0), "agent.llm.attempts": meta.get("attempts", 1),
                 "agent.llm.rate_limit_wait_s": meta.get("rate_limit_wait_s", 0), "agent.llm.latency_s": meta.get("latency_s", 0),
                 "agent.llm.tool_calls_requested": len(reply.tool_calls) if reply else 0, "agent.wrap_up": wrap_up}
        for k, v in attrs.items():
            span.set_attribute(k, _safe(v))
        if error is not None:
            span.set_status(Status(StatusCode.ERROR, _safe(f"{type(error).__name__}: {error}")))
            span.set_attribute("error.type", type(error).__name__)
        self._log_llm_call(span, reply, new_messages, meta, error)
        span.end()

    def _log_llm_call(self, span, reply, new_messages, meta, error) -> None:
        record = {"turn": span.attributes.get("agent.turn"), "time": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                  "model": meta.get("model"), "usage": {"input": meta.get("input_tokens"), "output": meta.get("output_tokens")},
                  "latency_s": meta.get("latency_s"), "attempts": meta.get("attempts"), "finish_reason": meta.get("finish_reason"),
                  "error": f"{type(error).__name__}: {error}" if error else None}
        if self.capture:
            record["new_messages"] = new_messages
            if reply is not None:
                record["reply"] = {"text": reply.text, "reasoning": reply.reasoning[:4000],
                                   "tool_calls": [{"id": c.id, "name": c.name, "args": c.args} for c in reply.tool_calls]}
        else:
            record["new_messages"] = [{"role": m.get("role"), "chars": len(str(m.get("content", "")))} for m in new_messages]
        line = redact(json.dumps(record, ensure_ascii=False, default=str))
        with (self.run_dir / "llm_calls.jsonl").open("a", encoding="utf-8") as f:
            f.write(line + "\n")

    # ── tool calls ───────────────────────────────────────────────────────────────
    def start_tool(self, turn: int, name: str, args: dict, call_id: str, server: str):
        span = self.tracer.start_span(f"execute_tool {name}", context=self.ctx, attributes={
            "gen_ai.operation.name": "execute_tool", "gen_ai.tool.name": name, "gen_ai.tool.call.id": call_id, "gen_ai.tool.type": "extension",
            "agent.turn": turn, "agent.tool.server": server,
            **({"gen_ai.tool.call.arguments": _safe(args)} if self.capture else {})})
        self._t0[span] = time.time()
        return span

    def end_tool(self, span, result: str, verdict: str, approval: str, error: bool) -> None:
        elapsed = time.time() - self._t0.pop(span, time.time())
        c = self.counters
        c["tool_calls"] += 1
        c["tool_time_s"] += elapsed
        c["tool_errors"] += 1 if error else 0
        c["guardrail_blocks"] += 1 if verdict == "blocked" else 0
        c["approvals_asked"] += 1 if approval in ("approved", "denied") else 0
        c["approvals_denied"] += 1 if approval == "denied" else 0
        span.set_attribute("agent.guardrail.verdict", verdict)
        span.set_attribute("agent.approval", approval)
        span.set_attribute("agent.tool.duration_s", round(elapsed, 3))
        span.set_attribute("agent.tool.result_chars", len(result))
        if self.capture:
            span.set_attribute("gen_ai.tool.call.result", _safe(result))
        if error or verdict == "blocked" or approval == "denied":
            span.set_status(Status(StatusCode.ERROR, _safe(result[:200])))
        span.end()

    def event(self, span, name: str, **attrs) -> None:
        """Record something that happened INSIDE a span, immediately (so a crash can't lose it)."""
        attrs = {k: _safe(v) for k, v in attrs.items()}
        if span is not None:
            span.add_event(name, attrs)
            self.proc.write({"t": "event", "span_id": f"{span.get_span_context().span_id:016x}", "name": name,
                             "time_ns": time.time_ns(), "attributes": attrs})

    # ── closing the run ──────────────────────────────────────────────────────────
    def finish(self, status: str, *, answer: str | None = None, error: BaseException | None = None, stop_reason: str | None = None,
               outputs: list[str] | None = None, turns: int | None = None) -> None:
        """Always call this (the runner does, in a `finally`). Never raises."""
        try:
            m, c = self.manifest, self.counters
            m["status"], m["stop_reason"] = status, stop_reason or STOP_REASONS.get(status, status)
            m["ended_at"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            m["duration_s"] = round(time.time() - self.started, 2)
            m["answer"] = _safe(answer) if answer else None
            m["outputs"] = outputs or []
            if turns is not None:
                c["turns"] = turns
            m["usage"] = {**{k: (round(v, 2) if isinstance(v, float) else v) for k, v in c.items()},
                          "total_tokens": c["input_tokens"] + c["output_tokens"]}
            if error is not None:
                m["error"] = {"type": type(error).__name__, "message": _safe(str(error)),
                              "traceback": _safe("".join(traceback.format_exception(error))[-6000:])}
                self.root.set_status(Status(StatusCode.ERROR, _safe(str(error)[:200])))
            elif status != "completed":
                self.root.set_status(Status(StatusCode.ERROR, status))
            for k, v in {"agent.status": status, "gen_ai.usage.input_tokens": c["input_tokens"], "gen_ai.usage.output_tokens": c["output_tokens"],
                         "agent.tool_calls": c["tool_calls"], "agent.guardrail_blocks": c["guardrail_blocks"], "agent.turns": c["turns"]}.items():
                self.root.set_attribute(k, v)
            self.root.end()
            self.provider.shutdown()
            self._write_manifest()
            build_trace_html(self.run_dir)
            build_runs_index(self.run_dir.parent)
        except Exception as exc:                                              # noqa: BLE001 – recording must never crash the run
            print(f"  [trace] could not finish writing the trace: {type(exc).__name__}: {exc}")

    def _write_manifest(self) -> None:
        atomic_write(self.run_dir / "run.json", redact(json.dumps(self.manifest, indent=2, ensure_ascii=False, default=str)))


STOP_REASONS = {"completed": "the model gave its final answer", "out_of_turns": "turn limit reached (wrap-up requested)",
                "out_of_budget": "token budget reached (wrap-up requested)",
                "out_of_context": "the conversation grew too large (wrap-up requested)", "failed": "an error stopped the run",
                "crashed": "the run was interrupted or crashed", "cancelled": "the run was cancelled"}


# ───────────────────────────── fingerprints & environment ─────────────────────────────
def _rel(p: Path) -> str:
    try:
        return p.relative_to(ROOT).as_posix()
    except ValueError:
        return str(p)


def fingerprints() -> dict:
    """Short hashes of everything that shaped this run, so two runs can be compared ("did the prompt change?")."""
    base, out = agent_dir(), {}
    files = [base / "agent.toml", base / "guardrails.toml", base / "mcp.json", base / "goal.md", ROOT / "app" / "prompts" / "system.md",
             *sorted((base / "prompts").rglob("*.md")), *sorted((base / "tools").glob("*.py"))]
    for f in files:
        if f.is_file():
            out[_rel(f)] = hashlib.sha256(f.read_bytes()).hexdigest()[:12]
    try:
        commit = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=ROOT, capture_output=True, text=True, timeout=3)
        if commit.returncode == 0:
            out["git_commit"] = commit.stdout.strip()
    except Exception:                                                        # noqa: BLE001
        pass
    return out


def environment() -> dict:
    pkgs = {}
    for name in ("openai", "mcp", "a2a-sdk", "opentelemetry-sdk"):
        try:
            pkgs[name] = version(name)
        except PackageNotFoundError:
            pass
    return {"python": sys.version.split()[0], "platform": platform.platform(), "packages": pkgs}


# ───────────────────────────── viewer pages ─────────────────────────────
def _embed(template: str, data: dict) -> str:
    blob = json.dumps(data, ensure_ascii=False, default=str).replace("</", "<\\/")
    return (UI_DIR / template).read_text(encoding="utf-8").replace("/*__DATA__*/null", blob)


def read_spans(run_dir: Path) -> list[dict]:
    """Merge start/event/end lines into one record per span (a span with no end line = the run died while it was open)."""
    spans: dict[str, dict] = {}
    path = run_dir / "trace.jsonl"
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue                                                         # a half-written last line after a crash
        sp = spans.setdefault(r["span_id"], {"span_id": r["span_id"], "events": [], "finished": False}) if r["t"] != "event" else spans.get(r["span_id"])
        if sp is None:
            continue
        if r["t"] == "start":
            sp.update({k: r[k] for k in ("trace_id", "parent_id", "name", "start_ns", "attributes")})
        elif r["t"] == "event":
            sp["events"].append({k: r[k] for k in ("name", "time_ns", "attributes")})
        elif r["t"] == "end":
            sp.update({k: r[k] for k in ("trace_id", "parent_id", "name", "start_ns", "end_ns", "attributes", "events", "status", "status_description")})
            sp["finished"] = True
    return sorted(spans.values(), key=lambda s: s.get("start_ns", 0))


def read_llm_calls(run_dir: Path) -> list[dict]:
    path = run_dir / "llm_calls.jsonl"
    out = []
    for line in path.read_text(encoding="utf-8").splitlines() if path.exists() else []:
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def build_trace_html(run_dir: Path) -> Path:
    manifest = json.loads((run_dir / "run.json").read_text(encoding="utf-8"))
    system = (run_dir / "system_prompt.txt").read_text(encoding="utf-8") if (run_dir / "system_prompt.txt").exists() else ""
    page = run_dir / "trace.html"
    atomic_write(page, _embed("trace_viewer.html", {"manifest": manifest, "spans": read_spans(run_dir), "llm_calls": read_llm_calls(run_dir), "system_prompt": system}))
    return page


def list_runs(base: Path) -> list[dict]:
    runs = []
    for f in sorted(base.glob("*/run.json"), reverse=True):
        try:
            m = json.loads(f.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            m = {"run_id": f.parent.name, "status": "unreadable"}
        runs.append(m)
    return runs


def build_runs_index(base: Path) -> Path:
    rows = [{"run_id": m.get("run_id"), "status": m.get("status"), "started_at": m.get("started_at"), "duration_s": m.get("duration_s"),
             "goal": m.get("goal"), "agent": (m.get("agent") or {}).get("name"), "entry": (m.get("entry") or {}).get("type"),
             "tokens": (m.get("usage") or {}).get("total_tokens"), "tool_calls": (m.get("usage") or {}).get("tool_calls"),
             "blocks": (m.get("usage") or {}).get("guardrail_blocks"), "model": (m.get("model") or {}).get("name"),
             "has_trace": (base / str(m.get("run_id")) / "trace.html").exists()} for m in list_runs(base)]
    page = base / "index.html"
    atomic_write(page, _embed("runs_index.html", {"runs": rows}))
    return page
