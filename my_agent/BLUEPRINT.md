# Agent blueprint — fill this in with your team

> **How to fill this in is explained in the handbook** (link shared in the workshop).
> Do it before you write any prompt. Everything you decide here becomes a file — see the last table.

---

## 1. The goal — one sentence
*What goes in, what must come back out?*

> 

---

## 2. Shape of the work
Tick what fits (you can mix):

- [ ] **A line** — step 1, then 2, then 3
- [ ] **A loop** — try → check → fix → check…
- [ ] **Side by side** — independent things at the same time
- [ ] **A fork** — after the evidence, go left or right

---

## 3. The phases

| # | Phase name | What goes IN | What comes OUT | Who decides here?<br><sub>tool · AI thinks · rule · human</sub> | Tool / MCP | Done when… |
|---|---|---|---|---|---|---|
| 1 |  |  |  |  |  |  |
| 2 |  |  |  |  |  |  |
| 3 |  |  |  |  |  |  |
| 4 |  |  |  |  |  |  |
| 5 |  |  |  |  |  |  |

---

## 4. Where does the AI really have to think?
*Circle the phases above that need judgement. Those are the ones to describe most carefully.*

> 

---

## 5. Shopping list

**Built-in tools available:** `list_files` · `read_file` · `search_text` · `write_file` · `edit_file` · `run_command`

| We need to… | We'll use… |
|---|---|
|  |  |
|  |  |
|  |  |
|  |  |

**Our tools (max 4):** 

**Our MCP server (max 1, or none):** 

**Tools we must write ourselves:** 

---

## 6. `.env` variables we need

- [ ] `NVIDIA_API_KEY` — always
- [ ] ______________________ — for our MCP server *(read-only token)*
- [ ] nothing else

---

## 7. Safety and hand-over

**The agent must NEVER:**
> 

**It must stop and ask a human when:**
> 

**It may only change these files:**
> 

---

## 8. Who does what

| Phase | Owner | Status (todo · doing · reviewed ✔) |
|---|---|---|
| 1 |  |  |
| 2 |  |  |
| 3 |  |  |
| 4 |  |  |
| 5 |  |  |

**Orchestrator:** 

---

## 9. Where each answer goes

| This blueprint | → | The file to write |
|---|---|---|
| 1 · the goal | → | `goal.md` + **Mission** in `prompts/agent.md` |
| 3 · the phases | → | numbered **Phases** in `prompts/agent.md` (each with its *Done when…*) |
| 4 · where the AI thinks | → | the wording of those phases + `prompts/skills/*.md` |
| 5 · the shopping list | → | `agent.toml` `[tools]` · `tools/*.py` · `mcp.json` |
| 6 · variables | → | `.env` |
| 7 · safety and hand-over | → | `guardrails.toml` + **Rules** and **Escalate when…** in `prompts/agent.md` |
