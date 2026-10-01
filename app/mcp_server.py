"""MODULE 7a · LOCAL MCP SERVER – serves every @tool function over the Model Context Protocol (MCP).

MCP is a standard "plug" between an agent and its tools. This server starts as a small background
process; the agent connects to it (see mcp_client.py), asks "what tools do you have?", and calls them.
You never start this by hand – the agent does – but you can:  python -m app.mcp_server
"""
from mcp.server.fastmcp import FastMCP

from app.config import load_profile, load_settings
from app.tools.registry import discover

server = FastMCP("agent-tools", log_level="WARNING")

enabled = load_profile()["tools"]["enabled"]
for fn in discover():
    if enabled and fn.__name__ not in enabled:
        continue                  # not listed in agent.toml → the model never sees it
    if fn.__name__ == "load_skill" and load_settings().skills_mode != "on_demand":
        continue                  # skills are already inside the prompt, no need to offer the tool
    server.add_tool(fn)           # name = function name, description = docstring, schema = type hints

if __name__ == "__main__":
    server.run(transport="stdio")
