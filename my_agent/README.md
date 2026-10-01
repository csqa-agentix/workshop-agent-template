# 🟢 my_agent — YOUR agent lives here

**This is the only folder you need to edit.** Everything else in the project is the engine (`app/`), reference material, or automatic.

| File / folder | What it is | When you touch it |
|---|---|---|
| `BLUEPRINT.md` | blank planning worksheet (how to fill it in is in the handbook) | **first** — fill it in with your team |
| `goal.md` | the task you hand to the agent | whenever the task changes |
| `prompts/agent.md` | the agent's job description: mission, **phases**, rules, hand-over, answer format | **the most important file** |
| `prompts/skills/*.md` | reusable know-how (decision tables, checklists, report layouts) | when the agent needs expert knowledge |
| `agent.toml` | the agent's name, what it can do (its "business card"), which tools it may use (max 4) | once, early |
| `tools/` | your own Python tools (`_example_tool.py` = copy me) | only if no built-in tool can do the job |
| `guardrails.toml` | rules it can never break: which files it may change, which commands it may run, what needs approval | once, early |
| `mcp.json` | external MCP servers (Playwright, GitHub, your own) | only if you need one — see `docs/MCP.md` |
| `workspace/` | the input files the agent works on (it works on a *copy*; originals are safe) | put your sample material here |
| `prompts/offline_script.json` | a pretend-model script so you can demo without a key | optional |

The default content is a tiny **placeholder agent** (it briefs you on the files in `workspace/`). It exists so everything runs on day one.
**Replace it with yours.**
