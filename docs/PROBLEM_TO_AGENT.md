# From a problem statement to an agent — the mapping method

*(Fill in `my_agent/BLUEPRINT.md` first; this page shows how the problem statements map onto the template's files.)*

Every workshop problem is written the same way, so the same method works for all of them (and for problems you invent).
Read the statement, then fill the right-hand column. **No new Python is needed for most of it** — and everything lives in `my_agent/`.

| The statement says… | In the template it becomes… |
|---|---|
| “How the agent works, step by step” (6 steps) | the **Phases** of `my_agent/prompts/agent.md`, each with *Done when…* |
| “It can handle” | what the phases do on their own |
| “It must hand to a human” | the **Escalate when…** section + a clear final-answer format for hand-over notes |
| “It must never” | **Rules** in `agent.md` **and** enforcement in `my_agent/guardrails.toml` (+ a test) |
| “What you will receive” (inputs) | files copied into `my_agent/workspace/` |
| “What your team hands in” (outputs) | `Final answer format` + files written to `output/` + `result.json` |
| “How your work will be judged” | your own test checklist; each row suggests a rule or a phase |
| “Keep it simple: one agent, one Skill, ≤ 4 tools, ≤ 1 MCP” | `my_agent/agent.toml` `[tools].enabled` (max 4), one skill file, the single local MCP server |
| “Retry at most twice” | wording in the phase + `[budgets.per_tool]` |
| “Never claim success without proof” | evidence rule in `agent.md` + `[claims]` |

## The five workshop statements, mapped (illustrations — they show the method, not the only answer)

| Problem | Tools it is likely to need (built-in unless noted) | What to configure | The “never” list → guardrail |
|---|---|---|---|
| **1 · Playwright failure triage** (diagnose, fix safely, prove, hand over) | `read_file`, `search_text`, `edit_file`, `run_command` | `[commands] allowed`: the organisers' run-one-test and regression commands (e.g. `"npx playwright test"`); `[files] writable`: only the test files the statement lists; skill: failure taxonomy (changed element / timing / data / setup / real bug / unknown) with fix rules | skip/disable tests, weaken checks, edit the site's code, add fixed sleeps → `[files] writable` (site code unreachable) + prompt rule + `[claims]` for “fixed” |
| **2 · Ask the Requirements** (search docs, cite, review test cases) | `list_files`, `read_file`, `search_text`; optional custom `check_citations(doc, section, quote)` | skill: answer/abstain/conflict rules and citation format; “try once more” as a phase; JSON output with requirement map, gaps, conflicts | invent requirement/citation, use general knowledge → prompt rule + a citation-checking tool whose result must appear before the final answer |
| **3 · API test builder** (OpenAPI → Postman → Newman → repair) | `read_file`, `write_file`, `run_command`; optional custom `validate_collection(path)` | `[commands] allowed`: `"newman run"`; `[files] writable`: `output/`; placeholders for secrets (the secret filter already ignores `{{placeholder}}` values); `[budgets.per_tool]` for repair runs | real secrets in files, mutating calls outside the practice API, hiding failing checks → secret filter, `[commands] allowed` (no other hosts/programs), prompt rule |
| **4 · Pull request risk review** (read story + diff, explore, run tests, report) | `read_file`, `search_text`, `run_command` (read-only git + tests), `write_file` | `[commands] allowed`: `"git diff"`, `"git log"`, the test command; `[files] writable`: `output/` (local tests only); final answer = prioritised findings with file+line | approve/merge, comment on the shared PR, fake test results → no such tool exists; prompt rule; `[claims]` |
| **5 · Change impact planner** (read-only discovery → plan) | `list_files`, `search_text`, `read_file`, `write_file` (for `output/`) | skill: fact / inference / assumption labelling; plan layout; open-questions style | change code, invent files, present guesses as facts → `[files] writable = ["output/"]` (code is read-only by construction) + a “every cited path must exist” rule (optionally a custom `verify_paths` tool) |

### What to write in the prompt (a good Phase)
```
3. **Decide the failure type** – Using the evidence from phase 2, choose exactly one of: changed-element, timing, test-data, setup, real-bug, unknown.
   Quote the line of the error message or snapshot that proves it. If your confidence is below "high", choose `unknown`.
   *Done when:* you have a type, a quote, and a confidence level.
```
Specific, observable, with a stop condition — and a way to say “I'm not sure”.
