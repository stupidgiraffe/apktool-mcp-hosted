"""HTTP/ASGI entrypoint for the upstream APKTool MCP server.

For MCPHosting: auto-discovery can import mcp or app from this module.
For a normal process host: python server.py starts Streamable HTTP at /mcp.
"""
import os
import shutil
import stat
import tempfile
from pathlib import Path

def prepare_runtime() -> None:
    bin_dir = Path(tempfile.gettempdir()) / "apktool-mcp-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / "apktool"
    source = Path(__file__).with_name("apktool_launcher.py")
    shutil.copyfile(source, launcher)
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault("APKTOOL_WORKSPACE", str(Path(tempfile.gettempdir()) / "apktool-mcp-workspace"))

prepare_runtime()
from apktool_mcp_server import mcp  # noqa: E402

app = mcp.http_app()

if __name__ == "__main__":
    mcp.run(transport="streamable-http", host="0.0.0.0", port=int(os.environ.get("PORT", "8000")))
