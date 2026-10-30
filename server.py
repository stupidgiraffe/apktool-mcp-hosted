"""Render deployment entrypoint for the Apktool MCP server.

The private MCP URL contains a random path component stored only in Render's
MCP_PATH_TOKEN environment variable. This is a capability URL, not OAuth.
"""
import os
import shutil
import stat
import tempfile
from pathlib import Path

from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Mount, Route


def prepare_runtime() -> None:
    bin_dir = Path(tempfile.gettempdir()) / "apktool-mcp-bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    launcher = bin_dir / "apktool"
    source = Path(__file__).with_name("apktool_launcher.py")
    shutil.copyfile(source, launcher)
    launcher.chmod(launcher.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    os.environ["PATH"] = str(bin_dir) + os.pathsep + os.environ.get("PATH", "")
    os.environ.setdefault(
        "APKTOOL_WORKSPACE",
        str(Path(tempfile.gettempdir()) / "apktool-mcp-workspace"),
    )


prepare_runtime()
from apktool_mcp_server import mcp  # noqa: E402
from transfer_tools import register, serve_artifact  # noqa: E402

register(mcp)

access_token = os.environ.get("MCP_PATH_TOKEN", "")
if len(access_token) < 24 or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_" for c in access_token):
    raise RuntimeError("MCP_PATH_TOKEN must be set to a random URL-safe token of at least 24 characters")

mcp_app = mcp.http_app(path="/mcp")


async def health(request):
    return PlainTextResponse("ready")


app = Starlette(
    routes=[
        Route("/", endpoint=health, methods=["GET"]),
        Route("/health", endpoint=health, methods=["GET"]),
        Route("/private/" + access_token + "/downloads/{artifact_id}", endpoint=serve_artifact, methods=["GET"]),
        Mount("/private/" + access_token, app=mcp_app),
    ],
    lifespan=mcp_app.lifespan,
)
