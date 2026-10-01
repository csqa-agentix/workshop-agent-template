# 🟡 examples/ — DUMMY examples, for reading only

> **Do not start here. Do not edit these.** Your agent goes in **`my_agent/`**.

These are two small, finished agents that exist only to *show* how the pieces fit. They have nothing to do with your problem statement.
Each one is a complete agent folder with exactly the same shape as `my_agent/`, so you can compare them file by file.

| Example | What it shows | Try it |
|---|---|---|
| `example-triage-report/` | a **custom tool** (`tools/summarize_csv.py`), a **skill**, and a structured report | `python -m app --agent examples/example-triage-report --offline` |
| `example-security-demo/` | the **safeguards**: a booby-trapped file tries to trick the agent; every attempt is blocked | `python -m app --agent examples/example-security-demo --offline --yes` |

Run one, then open `runs/<latest>/trace.html` to see what happened — and read the example's `prompts/agent.md` to see how its phases are written.
