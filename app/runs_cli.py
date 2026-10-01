"""MODULE 9 · TRACING (the runs command) – look at past runs from the terminal.

    python -m app runs                     list all runs (newest first)
    python -m app runs show latest         the steps of one run, as a tree         (or an id / the start of an id)
    python -m app runs open latest         open the picture of the run in your browser   (or:  open index)
    python -m app runs export latest       make runs/<id>.zip – an evidence bundle you can hand in (secrets already blanked)
    python -m app runs prune --keep 20     delete all but the newest 20 runs
"""
from __future__ import annotations

import argparse
import shutil
import webbrowser
import zipfile
from pathlib import Path

from app.telemetry import build_runs_index, build_trace_html, list_runs, read_spans, runs_dir


def resolve(base: Path, ident: str) -> Path:
    folders = sorted((p for p in base.iterdir() if (p / "run.json").exists()), reverse=True) if base.exists() else []
    if not folders:
        raise SystemExit("There are no runs yet. Try:  python -m app --offline")
    if ident == "latest":
        return folders[0]
    matches = [p for p in folders if p.name.startswith(ident)]
    if len(matches) != 1:
        raise SystemExit(f"'{ident}' matches {len(matches)} runs. Use  python -m app runs  to see the ids.")
    return matches[0]


def fmt(seconds) -> str:
    return "–" if seconds is None else (f"{seconds * 1000:.0f} ms" if seconds < 1 else f"{seconds:.1f} s")


def main(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="python -m app runs")
    sub = p.add_subparsers(dest="cmd")
    for name in ("show", "open", "export"):
        sp = sub.add_parser(name)
        sp.add_argument("run", help="'latest', a run id, or the start of one" + (" (or 'index')" if name == "open" else ""))
        if name == "export":
            sp.add_argument("--with-workspace", action="store_true", help="also include the working copy of the files")
    pr = sub.add_parser("prune")
    pr.add_argument("--keep", type=int, default=20)
    args = p.parse_args(argv)
    base = runs_dir()

    if args.cmd in (None, "list"):
        rows = list_runs(base)
        if not rows:
            print("No runs yet. Try:  python -m app --offline")
            return 0
        print(f"{'RUN':<22} {'STATUS':<14} {'TIME':>8} {'TOKENS':>8} {'TOOLS':>5} {'BLOCKS':>6}  GOAL")
        for m in rows:
            u = m.get("usage") or {}
            print(f"{m.get('run_id', '?'):<22} {m.get('status', '?'):<14} {fmt(m.get('duration_s')):>8} {u.get('total_tokens', '–'):>8} "
                  f"{u.get('tool_calls', '–'):>5} {u.get('guardrail_blocks', '–'):>6}  {(m.get('goal') or '')[:60]}")
        print(f"\nPicture of all runs: {base / 'index.html'}   (python -m app runs open index)")
    elif args.cmd == "show":
        run = resolve(base, args.run)
        import json
        m = json.loads((run / "run.json").read_text(encoding="utf-8"))
        u = m.get("usage") or {}
        print(f"\n{m['run_id']}  [{m['status']}]  {fmt(m.get('duration_s'))}  — {m.get('stop_reason')}\nGoal: {m.get('goal')}")
        print(f"Model: {m['model']['name']} · turns {u.get('turns')} · tokens {u.get('input_tokens')}→{u.get('output_tokens')} · tools {u.get('tool_calls')} "
              f"({u.get('tool_errors')} errors) · blocks {u.get('guardrail_blocks')} · rate-limit wait {fmt(u.get('rate_limit_wait_s'))}\n")
        spans = read_spans(run)
        by_id = {s["span_id"]: s for s in spans}
        for s in spans:
            depth, parent = 0, s.get("parent_id")
            while parent and parent in by_id:
                depth, parent = depth + 1, by_id[parent].get("parent_id")
            a = s.get("attributes") or {}
            took = fmt((s["end_ns"] - s["start_ns"]) / 1e9) if s.get("finished") else "UNFINISHED"
            extra = "  ".join(x for x in (a.get("agent.guardrail.verdict") if a.get("agent.guardrail.verdict") not in (None, "allowed") else "",
                                           f"approval:{a['agent.approval']}" if a.get("agent.approval") not in (None, "not_required") else "",
                                           f"{a['gen_ai.usage.input_tokens']}→{a['gen_ai.usage.output_tokens']} tokens" if "gen_ai.usage.input_tokens" in a and depth else "") if x)
            print(f"{'  ' * depth}{s['name']:<40} {took:>11}  {extra}")
            for e in s.get("events") or []:
                print(f"{'  ' * depth}    ● {e['name']} {e['attributes'].get('reason', '')[:80]}")
        print(f"\nFull picture: {run / 'trace.html'}")
    elif args.cmd == "open":
        if args.run == "index":
            target = build_runs_index(base)
        else:
            run = resolve(base, args.run)
            target = build_trace_html(run)
        print(f"Opening {target}")
        webbrowser.open(target.as_uri())
    elif args.cmd == "export":
        run = resolve(base, args.run)
        build_trace_html(run)
        zip_path = base / f"{run.name}.zip"
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as z:
            for f in sorted(run.rglob("*")):
                rel = f.relative_to(run)
                if f.is_file() and (args.with_workspace or rel.parts[0] != "workspace") and f.suffix != ".tmp":
                    z.write(f, f"{run.name}/{rel.as_posix()}")
        print(f"Wrote {zip_path}  (everything in it already has secrets blanked out)")
    elif args.cmd == "prune":
        folders = sorted((p for p in base.iterdir() if (p / "run.json").exists()), reverse=True)
        for old in folders[args.keep:]:
            shutil.rmtree(old)
        build_runs_index(base)
        print(f"Kept the newest {min(len(folders), args.keep)} run(s); deleted {max(0, len(folders) - args.keep)}.")
    return 0
