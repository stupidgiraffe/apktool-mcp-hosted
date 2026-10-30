"""MCPHosting auto-discovery entry point.

Expose ONE FastMCP instance. The hosting provider owns the HTTP listener
and chooses its port; never start a second Uvicorn/FastMCP server here.

For local testing: fastmcp run server.py --transport http --port 8000
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
