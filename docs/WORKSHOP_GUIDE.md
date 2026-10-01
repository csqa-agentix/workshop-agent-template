# Speaker notes

The visual walkthrough for the room — the story, how to approach a problem, and the module-by-module handbook — is the website in the sibling folder **`workshop-agent-template-guide/`**.
This file is the short version for the speaker: the demo path and the questions that come up.

## Demo path (about 10 minutes)
1. `python -m app doctor` → green ticks (and what a ✗ looks like).
2. `python -m app --offline` → point at THINK / ACT / OBSERVE / GUARD lines.
3. Open `runs/<latest>/trace.html` → the timeline, the conversation, the numbers.
4. `python -m app --agent examples/example-security-demo --offline --yes` → the booby-trapped note and every blocked attempt, then open its `trace.html` and filter "Guardrails & errors".
5. `python -m app serve --offline` → web page, run a goal, tick *Show raw A2A messages*; in another terminal `python -m app.a2a_client "Brief me" --url http://localhost:8000`.
6. With the real model: change one line in a Phase of `my_agent/prompts/agent.md` → rerun → different behaviour, no Python changed.
7. Optional: copy a Playwright entry from `my_agent/mcp.examples.json` into `mcp.json`, `doctor`, run.

## Questions you'll hear
| Question | Answer |
|---|---|
| Where do I start? | `my_agent/BLUEPRINT.md` with the team, then `my_agent/prompts/agent.md`. Nothing else needs editing. |
| Why is the path in the prompt, not in code? | Because then a beginner can change the agent by editing English, and the same engine runs every agent. |
| Prompt vs skill? | `agent.md` = the job; a skill = reusable know-how the job refers to. |
| A2A vs MCP? | MCP = agent ↔ tools. A2A = agent ↔ agent (or any program). |
| Why can't I use all 60 Playwright tools? | The workshop caps tools at 4, and 60 tools confuse a model. Choose with `include`. |
| What's a 429? | Rate limit on the free tier. The agent waits and retries. |
| Why did it write nothing? | `[files] writable` in `guardrails.toml` — only `output/` by default. |
| Can I see what it was "thinking"? | `trace.html` → Conversation tab (and the model's private thinking when it provides it). |
