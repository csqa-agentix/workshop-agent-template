# Using MCP servers (Playwright, GitHub, or your own)

## What is this, in one minute?
Your agent already has built-in tools (read a file, search, write a file…). Sometimes it needs a **special power** that someone
else has already built: drive a web browser, read a GitHub pull request, query a database.
That power is packaged as an **MCP server**, and MCP is the **standard plug** that connects it to any agent.

Think of the kitchen: the agent is the chef, built-in tools are the knives, and an MCP server is **a new appliance you plug into the wall socket**.

There are three kinds of plug:

| Kind | Where it runs | How you connect | Example |
|---|---|---|---|
| **Program on your computer** | your laptop (started for you) | `"command"` + `"args"` | Playwright (`npx @playwright/mcp`) |
| **Remote server** | on the internet | `"url"` (+ a key in `"headers"`) | GitHub (`https://api.githubcopilot.com/mcp/`) |
| **Your own** | your laptop | `"command": "python"` + your file | a 15-line server below |

## How to add one — 3 steps
1. **Open `my_agent/mcp.examples.json`**, copy ONE entry (e.g. `"playwright"`) into **`my_agent/mcp.json`**, inside `"mcpServers"`.
2. **Choose which of its tools your agent may use** (`"include"`). *This is required* — see "Why include?" below.
3. **Check it:** `python -m app doctor`. You should see a line like
   `✓ MCP server 'playwright' (stdio): offers 25 tool(s), agent gets: browser_navigate, browser_snapshot`.

That's all. Now mention the new tools in `my_agent/prompts/agent.md` (which phase uses them) and run your agent.

## `mcp.json` explained
```json
{
  "mcpServers": {
    "playwright": {
      "command": "npx",
      "args": ["@playwright/mcp@latest", "--headless", "--isolated"],
      "include": ["browser_navigate", "browser_snapshot", "browser_click"],
      "approval": "ask",
      "auto_approve": ["browser_snapshot"]
    }
  }
}
```

| Setting | Meaning |
|---|---|
| `command`, `args`, `env` | how to start a server **on your computer** (`env` = extra variables it gets; nothing else from your `.env` is passed on) |
| `url`, `headers` | the address of a **remote** server and its key. Use `"Authorization": "Bearer ${GITHUB_TOKEN}"` — the real value comes from your `.env`, so **the secret is never written in this file** |
| `type` | `"http"` (default for a url) or `"sse"` for older servers |
| **`include`** | **the list of tool names the agent may use. Required.** Without it the agent gets none of the server's tools (and `doctor` tells you the names to pick) |
| `approval` | `"ask"` (default): a human must approve every call · `"never"`: no questions |
| `auto_approve` | with `"ask"`: these tools never ask (good for read-only tools like a page snapshot) |
| `prefix` | put a word in front of the tool names, e.g. `"gh_"` (use when two servers have a tool with the same name) |
| `optional` | `true` = if this server can't start, skip it instead of stopping |

`${NAME}` anywhere in a value is replaced from your environment / `.env`. If the variable is missing you get a friendly message telling you to add it.

## Why `include`? (the 60-tools problem)
Playwright's server offers **60+ tools** (25 in some versions). Giving a model 60 tools makes it confused, slow, and uses up your free quota
on the tool descriptions alone. The workshop also limits you to **4 tools in total**. So you pick the few you really need:

```
your 4 tools = built-in tools you enabled in agent.toml  +  the tools you list in "include"
```
Example: a browser agent might use `list_files` (to find test files) + `write_file` (report) + `browser_navigate` + `browser_snapshot` = 4.
`python -m app doctor` counts for you and warns when you are over.

## Recipe 1 — Playwright (a browser the agent can drive)
Needs [Node.js](https://nodejs.org) installed (`node --version`). The first start downloads the server, so it can take a minute.
```json
"playwright": {
  "command": "npx",
  "args": ["@playwright/mcp@latest", "--headless", "--isolated"],
  "include": ["browser_navigate", "browser_snapshot", "browser_click"],
  "approval": "ask",
  "auto_approve": ["browser_snapshot"]
}
```
- `--headless` = no visible window · `--isolated` = a fresh private browser every run.
- Restrict where it may go with `"--allowed-origins", "http://localhost:3000"` in `args` (this limits basic requests; it is **not** a security wall).
- A snapshot gives the agent a text outline of the page it can read ("button 'Order'").
- ⚠ A web page is *untrusted text*. The agent treats it as data (see `docs/SECURITY.md`), but keep `approval` on for anything that clicks or types.

## Recipe 2 — GitHub (read a pull request)
Needs a **read-only** token. Put it in `.env` as `GITHUB_TOKEN=github_pat_…` (never in the chat, never in `mcp.json`).
> ⚠ A personal token is a real credential. For the workshop, ask the organisers whether they provide a shared read-only token; otherwise skip this recipe.
```json
"github": {
  "url": "https://api.githubcopilot.com/mcp/",
  "headers": { "Authorization": "Bearer ${GITHUB_TOKEN}" },
  "include": ["get_pull_request", "get_pull_request_files"],
  "approval": "ask"
}
```
- Tool names change between versions — run `python -m app doctor` with an empty `include` and it prints what the server offers.
- Prefer read-only tools. Never include tools that comment, merge, or push.

## Recipe 3 — your own MCP server (15 lines)
Save as `my_agent/my_mcp_server.py`:
```python
from mcp.server.fastmcp import FastMCP

server = FastMCP("my-tools")

@server.tool()
def check_citation(document: str, section: str) -> str:
    """Say whether a section exists in a document (replace this body with your own logic)."""
    return f"Section {section} of {document}: found"      # always return REAL output, never a guess

if __name__ == "__main__":
    server.run(transport="stdio")
```
Then in `mcp.json`:
```json
"my-own-server": { "command": "python", "args": ["my_agent/my_mcp_server.py"], "include": ["check_citation"], "approval": "ask" }
```
*(For a simple tool you don't need MCP at all: a file in `my_agent/tools/` is easier. Use your own MCP server when you already have one, or want other programs to reuse it.)*

## Safety notes (the built-in protections)
- External tools **ask for approval by default** (a risky click shouldn't happen silently). In the terminal you type `y`; on the web page you press a button; over A2A the task pauses in `input-required`.
- Everything an MCP tool returns passes through the same filters as other tools: secrets are blanked out, and text that tries to give the agent orders is flagged.
- Tokens from `.env` are registered as secrets: if one ever shows up in output, it is replaced by `[REDACTED]`.
- External tools do **not** go through the file jail (`workspace/`) — that is why `include` and `approval` matter. Choose the narrowest tools.
- Which servers and tools were used is recorded in every run's `run.json` (never the tokens).

## Troubleshooting
| You see | Do this |
|---|---|
| `the program 'npx' is not installed` | Install Node.js from nodejs.org, then open a new terminal. |
| `did not answer within 90s` | First `npx` start downloads the server. Try again; check your internet. |
| `HTTP 401 – the server did not accept your token` | The token in `.env` is wrong/expired, or the variable name differs from `${…}` in `mcp.json`. |
| `needs the variable GITHUB_TOKEN` | Add `GITHUB_TOKEN=…` to your `.env` file. |
| `has no tool named […]. It offers: […]` | Fix the names in `include` using the list shown. |
| `NO tools are included` | Add an `include` list. |
| `Two MCP tools are both called…` | Add a `"prefix"` to one of the servers. |
| `⚠ N tools are active; the workshop limit is 4` | Remove tools from `[tools].enabled` in `agent.toml` or from `include`. |
