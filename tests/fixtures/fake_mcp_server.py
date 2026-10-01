"""A pretend 'Playwright-like' MCP server for tests: several tools, one with an awkward name, one that leaks a token.
Run as stdio:   python fake_mcp_server.py
Run as HTTP:    python fake_mcp_server.py http <port>      (requires header  Authorization: Bearer test-token-123456)"""
import sys

from mcp.server.fastmcp import FastMCP

server = FastMCP("fake", log_level="WARNING", **({"port": int(sys.argv[2]), "host": "127.0.0.1"} if sys.argv[1:2] == ["http"] else {}))


@server.tool()
def echo(text: str) -> str:
    """Echo the text back."""
    return f"echo: {text}"


@server.tool()
def add(a: int, b: int) -> str:
    """Add two numbers."""
    return str(a + b)


@server.tool(name="browser.snapshot")
def snapshot() -> str:
    """A tool whose name contains a dot (invalid for OpenAI tool names)."""
    return "page snapshot"


@server.tool()
def leak() -> str:
    """Returns text containing a secret, to prove redaction."""
    return "here is a token: nvapi-" + "L" * 30


@server.tool()
def dangerous() -> str:
    """Pretend to change something outside the sandbox."""
    return "did something dangerous"


if __name__ == "__main__":
    if sys.argv[1:2] == ["http"]:
        import uvicorn

        app = server.streamable_http_app()

        class NeedsToken:
            async def __call__(self, scope, receive, send):
                if scope["type"] == "http":
                    headers = {k.decode().lower(): v.decode() for k, v in scope["headers"]}
                    if headers.get("authorization") != "Bearer test-token-123456":
                        await send({"type": "http.response.start", "status": 401, "headers": [(b"content-type", b"text/plain")]})
                        await send({"type": "http.response.body", "body": b"unauthorized"})
                        return
                await app(scope, receive, send)
        uvicorn.run(NeedsToken(), host="127.0.0.1", port=int(sys.argv[2]), log_level="error")
    else:
        server.run(transport="stdio")
