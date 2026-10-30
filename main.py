"""Alternative auto-discovery entrypoint for Python MCP hosts."""
from server import app, mcp

if __name__ == "__main__":
    import os
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
