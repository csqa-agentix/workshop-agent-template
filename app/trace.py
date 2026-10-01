"""MODULE 9 · TRACING (narrative) – the readable story of a run.

Prints the live THINK / ACT / OBSERVE / GUARD lines while the agent works and writes runs/<id>/report.md.
The complete machine record (spans, model calls, manifest, viewer page) is written by telemetry.py.
"""
from __future__ import annotations

import json
import os
import uuid
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Callable

from app.config import ROOT
from app.guardrails import redact

STOP_REASONS = {"completed": "the model gave its final answer", "out_of_turns": "turn limit reached (wrap-up requested)",
                "out_of_budget": "token budget reached (wrap-up requested)",
                "out_of_context": "the conversation grew too large (wrap-up requested)", "failed": "an error stopped the run"}
LABELS = {"think": "THINK  ", "act": "ACT    ", "observe": "OBSERVE", "guard": "GUARD  ", "final": "FINAL  ", "note": "NOTE   "}


def short(value, limit: int = 150) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


class Trace:
    def __init__(self, run_dir: Path | None = None, quiet: bool = False, sink: Callable[[dict], None] | None = None):
        self.run_dir = run_dir or Path(os.environ.get("RUNS_DIR", ROOT / "runs")) / f"{datetime.now():%Y%m%d-%H%M%S}-{uuid.uuid4().hex[:4]}"
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.quiet, self.events, self.sink = quiet, [], sink     # sink = live feed for the A2A server / UI

    def log(self, kind: str, turn: int, **data) -> None:
        event = {"kind": kind, "turn": turn, **data}
        self.events.append(event)
        if self.sink:
            safe = {k: v for k, v in event.items() if k != "model_reasoning"}
            self.sink(json.loads(redact(json.dumps(safe, ensure_ascii=False))))      # secrets never leave the process, even nested in args
        if not self.quiet:
            detail = {"think": data.get("text"), "act": f'{data.get("tool")}({short(data.get("args", {}), 100)})',
                      "observe": data.get("summary"), "guard": data.get("reason"),
                      "final": data.get("text"), "note": data.get("text")}[kind]
            print(f"[{turn:>2}] {LABELS[kind]} {redact(short(detail or '', 200))}")

    def write_report(self, goal: str, status: str, answer: str, changes: str = "", outputs: list[str] | None = None) -> Path:
        tools = Counter(e["tool"] for e in self.events if e["kind"] == "act")
        blocked = [e for e in self.events if e["kind"] == "guard"]
        lines = [f"# Agent run report", f"- **Goal:** {goal}", f"- **Status:** {status}",
                 f"- **Turns:** {max((e['turn'] for e in self.events), default=0)}",
                 f"- **Tool calls:** {sum(tools.values())} ({', '.join(f'{k}×{v}' for k, v in tools.items()) or 'none'})",
                 f"- **Guardrail blocks:** {len(blocked)}", f"- **Why it stopped:** {STOP_REASONS.get(status, status)}",
                 f"- **Files produced:** {', '.join(outputs) if outputs else 'none'}", "", "## Final answer", answer or "(none)", ""]
        if changes:
            lines += ["## Changes made to workspace files (diff)", "```diff", changes.rstrip(), "```", ""]
        lines += ["## Steps"]
        for e in self.events:
            if e["kind"] in ("think", "act", "observe", "guard"):
                detail = {"think": e.get("text"), "act": f'`{e.get("tool")}` {short(e.get("args", {}), 200)}',
                          "observe": e.get("summary"), "guard": e.get("reason")}[e["kind"]]
                lines.append(f"- turn {e['turn']} · **{e['kind']}** · {short(detail or '', 300)}")
        path = self.run_dir / "report.md"
        path.write_text(redact("\n".join(lines)) + "\n", encoding="utf-8")
        return path


def tools_used(events: list[dict]) -> dict[str, int]:
    return dict(Counter(e["tool"] for e in events if e["kind"] == "act"))
