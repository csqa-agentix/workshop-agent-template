# Talking to your AI coding tool — a checklist (not a script)

You will work with an AI coding tool (Claude Code, Cursor, Copilot, Gemini, Antigravity…). It reads `AGENTS.md` by itself, so it already knows how this
repo works. **What it does not know is your problem.** That part is yours to say, in your own words.

## First: do the blueprint without the tool
Fill in `my_agent/BLUEPRINT.md` as a team. Most of your prompt is already written there.

## What a good first message contains
- [ ] **The problem statement** — paste it, or point the tool at the file.
- [ ] **The goal in one sentence** — what comes in, what must go out.
- [ ] **Your phases** — the steps from your blueprint, in order, each with its "done when".
- [ ] **Where the AI must think** vs. where a tool just fetches something.
- [ ] **The tools / MCP you decided on** (max 4 tools, max 1 external MCP) — and which phase uses which.
- [ ] **The "never" list** and **when to hand over to a human** — they become guardrails and an *Escalate when…* section.
- [ ] **Your sample input files** — where they are (they go in `my_agent/workspace/`).
- [ ] **The output you need** — report, JSON, files.
- [ ] **Who you are:** "I'm a beginner — explain what you change, in plain words."

## Good habits while building
- Ask it to **change one phase at a time**, run `python -m app --offline`, look at the result, then continue.
- If the agent behaves badly, say: *"Make phase 3 in agent.md more specific"* — **not** *"add more code"*. The path lives in the prompt.
- Ask it to **explain any Python it writes** and to keep it small.
- Never paste your API key into the chat. Put it in `.env`.
- Read `runs/<latest>/trace.html` yourself. It tells you what the agent really did.

## Things worth asking for
- "Write the offline script so I can demo without a key."
- "Add a test for every rule in guardrails.toml."
- "Check my agent against the problem statement's 'must never' list."
- "Run `python -m app doctor` and fix what it reports."
