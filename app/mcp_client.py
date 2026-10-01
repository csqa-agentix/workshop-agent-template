"""MODULE 7b · MCP CLIENT (the "tool hub") – connects the agent to its tools over MCP.

MCP (Model Context Protocol) is a standard plug between an agent and tools. The hub connects to:
  • local-tools  – OUR built-in tools + the ones in my_agent/tools/   (always on; started for you)
  • any servers listed in my_agent/mcp.json  – Playwright, GitHub, or your own (local program OR remote URL)

For every connection it: 1) asks "what tools do you have?"  2) keeps only the tools you INCLUDED
3) hands them to the model in OpenAI format  4) runs a tool when the model asks, and returns the real output.
See docs/MCP.md for copy-paste setups.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from mcp import ClientSession, StdioServerParameters
from mcp.client.sse import sse_client
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from app.config import ROOT, agent_dir
from app.guardrails import register_secret

LOCAL = "local-tools"
CONNECT_TIMEOUT = 90          # first run of `npx …` may download a package
CALL_TIMEOUT = 120
VAR = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)(?::-([^}]*))?\}")
BAD_NAME = re.compile(r"[^a-zA-Z0-9_-]")


def explain(exc: BaseException) -> str:
    """The first real cause inside (possibly nested) errors, with a hint a beginner can act on."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        hint = {401: "the server did not accept your token – check the key in .env", 403: "the token has no permission for this server",
                404: "the URL is wrong or the server has no MCP endpoint there"}.get(code, "see the server's documentation")
        return f"HTTP {code} – {hint}"
    if isinstance(exc, httpx.ConnectError):
        return "could not connect – is the URL right, and is the server running / are you online?"
    return f"{type(exc).__name__}: {exc}"


class ToolHubError(Exception):
    """A readable problem with an MCP server (wrong command, missing token, unknown tool name …)."""


def expand(value, server: str, secret: bool = False):
    """Replace ${NAME} (or ${NAME:-default}) in a string with the value from your environment / .env."""
    if not isinstance(value, str):
        return value

    def fill(m: re.Match) -> str:
        found = os.environ.get(m.group(1), m.group(2))
        if found is None:
            raise ToolHubError(f"MCP server '{server}' needs the variable {m.group(1)}. Add {m.group(1)}=… to your .env file.")
        if secret:
            register_secret(found)                 # from now on this exact value is blanked out of logs and answers
        return found
    return VAR.sub(fill, value)


@dataclass
class Exposed:
    name: str                  # the name the model sees
    original: str              # the name the server knows
    server: str
    session: ClientSession
    tool: object
    ask: bool                  # does a human have to approve calls to this tool?


@dataclass
class ServerInfo:
    name: str
    transport: str             # stdio | http | sse
    offered: list[str] = field(default_factory=list)
    exposed: list[str] = field(default_factory=list)
    warning: str = ""


class ToolHub:
    def __init__(self, servers: dict, extra_env: dict[str, str] | None = None, max_chars: int = 6000):
        self.servers, self.extra_env, self.max_chars = servers, extra_env or {}, max_chars
        self._tools: dict[str, Exposed] = {}
        self.info: list[ServerInfo] = []
        self._stack = AsyncExitStack()

    # ── building the list of servers ─────────────────────────────────────────────
    @classmethod
    def for_agent(cls, **kwargs) -> "ToolHub":
        """local-tools (always) + whatever is in my_agent/mcp.json."""
        servers: dict = {LOCAL: {"command": "python", "args": ["-m", "app.mcp_server"], "_local": True}}
        path = agent_dir() / "mcp.json"
        if path.exists():
            try:
                external = json.loads(path.read_text(encoding="utf-8") or "{}").get("mcpServers", {})
            except json.JSONDecodeError as exc:
                raise ToolHubError(f"my_agent/mcp.json is not valid JSON: {exc}") from exc
            for name, spec in external.items():
                if name == LOCAL:
                    raise ToolHubError(f"'{LOCAL}' is a reserved name; pick another name in mcp.json.")
                servers[name] = spec
        return cls(servers, **kwargs)

    @property
    def external_count(self) -> int:
        return sum(1 for n in self.servers if n != LOCAL)

    # ── connecting ───────────────────────────────────────────────────────────────
    async def __aenter__(self) -> "ToolHub":
        await self._stack.__aenter__()
        try:
            for name, spec in self.servers.items():
                try:
                    await self._connect(name, spec)
                except ToolHubError:
                    raise
                except asyncio.TimeoutError:
                    raise ToolHubError(f"MCP server '{name}' did not answer within {CONNECT_TIMEOUT}s. Is the command/URL right? "
                                       "(The first start of an `npx` server downloads it and can be slow – try again.)") from None
                except FileNotFoundError:
                    raise ToolHubError(f"MCP server '{name}': the program '{spec.get('command')}' is not installed "
                                       "(for npx servers install Node.js from nodejs.org).") from None
                except BaseException as exc:                              # noqa: BLE001 – turn any failure into a readable one
                    if isinstance(exc, (KeyboardInterrupt, SystemExit)):
                        raise
                    if spec.get("optional"):
                        self.info.append(ServerInfo(name, "?", warning=f"skipped (optional): {explain(exc)}"))
                        continue
                    raise ToolHubError(f"MCP server '{name}' could not be reached: {explain(exc)}") from None
        except BaseException:
            try:
                await self._stack.aclose()
            except BaseException:                       # noqa: BLE001 – the original problem is the one worth reporting
                pass
            raise
        return self

    async def _connect(self, name: str, spec: dict) -> None:
        """Connect to ONE server. It gets its own cleanup scope, so a failure here unwinds right away and cannot disturb the others."""
        local = AsyncExitStack()
        try:
            if "url" in spec:
                transport = "sse" if spec.get("type") == "sse" else "http"
                headers = {k: expand(v, name, secret=True) for k, v in spec.get("headers", {}).items()}
                url = expand(spec["url"], name)
                if transport == "sse":
                    read, write = await local.enter_async_context(sse_client(url, headers=headers))
                else:
                    client = await local.enter_async_context(httpx.AsyncClient(headers=headers, timeout=httpx.Timeout(30.0, read=300.0)))
                    read, write, _ = await local.enter_async_context(streamable_http_client(url, http_client=client))
            elif "command" in spec:
                transport = "stdio"
                command = sys.executable if spec["command"] in ("python", "python3") else expand(spec["command"], name)
                env = {k: expand(v, name, secret=True) for k, v in spec.get("env", {}).items()}
                if spec.get("_local"):
                    env = {**env, **self.extra_env}
                env["NO_DOTENV"] = "1"            # tool programs never read your .env; they get only what is listed here
                work = self.extra_env.get("WORKSPACE_DIR")
                cwd = str(ROOT) if spec.get("_local") else (work if work and Path(work).is_dir() else str(ROOT))
                params = StdioServerParameters(command=command, args=[expand(a, name) for a in spec.get("args", [])], cwd=cwd, env=env)
                read, write = await local.enter_async_context(stdio_client(params))
            else:
                raise ToolHubError(f"MCP server '{name}' needs either a 'command' (a program on this computer) or a 'url' (a remote server).")
            session = await local.enter_async_context(ClientSession(read, write))
            async with asyncio.timeout(CONNECT_TIMEOUT):
                await session.initialize()
                offered = (await session.list_tools()).tools
            self._expose(name, spec, session, offered, transport)
        except BaseException as first:
            cause = None
            try:
                await local.aclose()
            except BaseException as closing:            # noqa: BLE001 – the transport's task group often holds the REAL error (e.g. HTTP 401)
                cause = closing
            if isinstance(first, asyncio.CancelledError) and cause is not None:
                raise cause from None
            raise
        self._stack.push_async_callback(local.aclose)     # closed (in reverse order) when the hub closes

    def _expose(self, server: str, spec: dict, session: ClientSession, offered: list, transport: str) -> None:
        info = ServerInfo(server, transport, offered=[t.name for t in offered])
        local = bool(spec.get("_local"))
        include = None if local else spec.get("include")
        if not local:
            if not include:
                info.warning = (f"offers {len(offered)} tools but NO tools are included, so the agent gets none. "
                                f"Add an \"include\" list to mcp.json, e.g. {info.offered[:3]}")
            elif include != ["*"]:
                missing = [n for n in include if n not in info.offered]
                if missing:
                    raise ToolHubError(f"MCP server '{server}' has no tool named {missing}. It offers: {info.offered}")
        approval, auto = spec.get("approval", "ask"), set(spec.get("auto_approve", []))
        for t in offered:
            if not local and not (include and (include == ["*"] or t.name in include)):
                continue
            name = BAD_NAME.sub("_", f"{spec.get('prefix', '')}{t.name}")[:64]
            if name in self._tools:
                raise ToolHubError(f"Two MCP tools are both called '{name}' (server '{server}'). Add \"prefix\": \"{server}_\" to that server in mcp.json.")
            ask = False if local else (approval != "never" and t.name not in auto)
            self._tools[name] = Exposed(name, t.name, server, session, t, ask)
            info.exposed.append(name)
        self.info.append(info)

    async def __aexit__(self, *exc) -> None:
        await self._stack.aclose()

    # ── what the runner / loop needs ─────────────────────────────────────────────
    def openai_tools(self) -> list[dict]:
        """The tool list in the format the OpenAI SDK expects."""
        return [{"type": "function", "function": {"name": e.name, "description": e.tool.description or "", "parameters": e.tool.inputSchema}}
                for e in self._tools.values()]

    def names(self) -> list[str]:
        return sorted(self._tools)

    def server_of(self, name: str) -> str:
        e = self._tools.get(name)
        return e.server if e else "?"

    def needs_approval(self, name: str) -> bool:
        e = self._tools.get(name)
        return bool(e and e.ask)

    def describe(self) -> list[dict]:
        """For run.json: which servers, how they connect, which tools were exposed (never headers or tokens)."""
        return [{"server": i.name, "transport": i.transport, "tools_offered": len(i.offered), "tools_exposed": i.exposed, "warning": i.warning}
                for i in self.info]

    async def call(self, name: str, args: dict) -> str:
        """Run one tool and return its output as text (errors come back as text the model can read)."""
        e = self._tools.get(name)
        if e is None:
            return f"ERROR: unknown tool '{name}'. Available: {self.names()}"
        try:
            result = await asyncio.wait_for(e.session.call_tool(e.original, args), CALL_TIMEOUT)
        except asyncio.TimeoutError:
            return f"ERROR: the tool '{name}' did not answer within {CALL_TIMEOUT}s."
        except Exception as exc:                                       # noqa: BLE001
            return f"ERROR: the tool '{name}' failed: {type(exc).__name__}: {exc}"
        parts = []
        for c in result.content:
            kind = getattr(c, "type", "")
            if kind == "text":
                parts.append(c.text)
            elif kind == "image":
                parts.append("[image omitted – the model reads text only]")
            elif kind == "resource":
                parts.append(getattr(c.resource, "text", None) or f"[resource {getattr(c.resource, 'uri', '')} omitted]")
            else:
                parts.append(f"[{kind or 'content'} omitted]")
        text = "\n".join(p for p in parts if p) or (json.dumps(result.structuredContent) if getattr(result, "structuredContent", None) else "(no output)")
        if result.isError:
            text = f"ERROR: {text}"
        if len(text) > self.max_chars:      # keep the conversation small: fewer tokens, fewer rate limits
            text = text[: self.max_chars] + f"\n… [cut: {len(text) - self.max_chars} more characters. Ask for a narrower slice.]"
        return text
