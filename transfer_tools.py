"""ChatGPT file-param import and temporary artifact delivery for hosted APKTool MCP."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import secrets
import socket
import time
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
import storage_b2
from pydantic import BaseModel, ConfigDict
from starlette.responses import FileResponse, PlainTextResponse

MAX_APK_BYTES = 512_000_000  # ChatGPT attachment limit: 512 MB (decimal)
DOWNLOADS: dict[str, tuple[Path, float]] = {}


class ChatGPTFile(BaseModel):
    """The file shape required by ChatGPT's MCP file-input extension."""
    model_config = ConfigDict(extra="forbid")
    download_url: str
    file_id: str
    mime_type: str | None = None
    file_name: str | None = None


def workspace() -> Path:
    base = Path(os.environ.get("APKTOOL_WORKSPACE", "/tmp/apktool-mcp-workspace"))
    base.mkdir(parents=True, exist_ok=True)
    return base.resolve()


def validate_public_https(url: str) -> None:
    u = urlsplit(url)
    if u.scheme != "https" or not u.hostname or u.username or u.password:
        raise ValueError("A public HTTPS file-download URL is required")
    if u.port not in (None, 443):
        raise ValueError("Nonstandard URL ports are not allowed")
    addresses = socket.getaddrinfo(u.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(
        not ipaddress.ip_address(addr[4][0]).is_global for addr in addresses
    ):
        raise ValueError("Private or reserved file-download addresses are forbidden")


async def download_attachment(file: ChatGPTFile) -> dict:
    """Download a ChatGPT-supplied APK to the temporary server workspace."""
    folder = workspace() / "uploads"
    folder.mkdir(parents=True, exist_ok=True)
    target = folder / (secrets.token_hex(12) + ".apk")
    sha = hashlib.sha256()
    length = 0
    url = file.download_url
    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=15.0),
            follow_redirects=False,
        ) as client:
            for _ in range(5):
                validate_public_https(url)
                async with client.stream("GET", url) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get("location")
                        if not location:
                            raise ValueError("File-download redirect has no destination")
                        url = urljoin(url, location)
                        continue
                    response.raise_for_status()
                    declared_length = response.headers.get("content-length")
                    if declared_length and int(declared_length) > MAX_APK_BYTES:
                        raise ValueError("APK exceeds 512 MB upload limit")
                    with target.open("wb") as out:
                        async for chunk in response.aiter_bytes(chunk_size=1024 * 1024):
                            length += len(chunk)
                            if length > MAX_APK_BYTES:
                                raise ValueError("APK exceeds 512 MB upload limit")
                            out.write(chunk)
                            sha.update(chunk)
                    break
            else:
                raise ValueError("Too many file-download redirects")
        if length == 0 or not zipfile.is_zipfile(target):
            raise ValueError("The attachment is not an APK/ZIP archive")
        with zipfile.ZipFile(target) as apk:
            if "AndroidManifest.xml" not in apk.namelist():
                raise ValueError("Missing AndroidManifest.xml; not a valid APK")
        result = {
            "success": True,
            "apk_path": str(target),
            "file_name": file.file_name or target.name,
            "size_bytes": length,
            "sha256": sha.hexdigest(),
            "next_step": "Call decode_apk with apk_path set to the returned apk_path.",
            "storage": "Ephemeral until B2 credentials are configured.",
        }
        if storage_b2.enabled():
            try:
                import asyncio
                record = await asyncio.to_thread(storage_b2.save_file, str(target), "originals")
                result["b2_object_key"] = record["object_key"]
                result["storage"] = "Backed up persistently to private Backblaze B2."
            except Exception as exc:
                result["storage_warning"] = f"Backblaze backup failed; this file is local only: {exc}"
        return result
    except Exception:
        target.unlink(missing_ok=True)
        raise


def publish_artifact(file_path: str) -> dict:
    """Publish an output file within the APKTool workspace for 15 minutes."""
    path = Path(file_path).resolve()
    if not path.is_relative_to(workspace()):
        raise ValueError("Only workspace outputs can be published")
    if not path.is_file():
        raise ValueError("File is missing; Render may have slept or restarted")
    if not 0 < path.stat().st_size <= MAX_APK_BYTES:
        raise ValueError("Output file is empty or larger than 512 MB")
    for token, (_, expires) in list(DOWNLOADS.items()):
        if expires < time.time():
            DOWNLOADS.pop(token, None)
    token = secrets.token_urlsafe(20)
    DOWNLOADS[token] = (path, time.time() + 900)
    root = os.environ.get("MCP_PATH_TOKEN", "")
    host = os.environ.get("PUBLIC_BASE_URL", "")
    if not host.startswith("https://"):
        raise RuntimeError("PUBLIC_BASE_URL must be an HTTPS origin")
    return {
        "success": True,
        "download_url": f"{host.rstrip('/')}/private/{root}/downloads/{token}",
        "expires_in_seconds": 900,
        "file_name": path.name,
    }


async def serve_artifact(request):
    token = request.path_params["artifact_id"]
    entry = DOWNLOADS.get(token)
    if not entry:
        return PlainTextResponse("Download missing or expired", status_code=404)
    path, expires = entry
    if time.time() > expires or not path.is_file():
        DOWNLOADS.pop(token, None)
        return PlainTextResponse("Download expired", status_code=404)
    return FileResponse(str(path), media_type="application/octet-stream", filename=path.name)


def register(mcp):
    @mcp.tool(
        meta={"openai/fileParams": ["file"]},
        annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True},
    )
    async def import_apk_attachment(file: ChatGPTFile) -> dict:
        """Import an .apk attached to this ChatGPT conversation into the hosted APKTool workspace. Use this first when the user attaches an APK and asks to decode, analyze, or edit it. ChatGPT supplies a temporary download URL for the attachment: don't ask the user to upload it again. Pass the returned apk_path to decode_apk."""
        return await download_attachment(file)

    @mcp.tool(
        annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
    )
    def get_apk_download_link(file_path: str) -> dict:
        """Get a temporary HTTPS download link for an APK rebuilt by build_apk or an output report saved in the APKTool workspace. Use this to return the finished file to the user."""
        if storage_b2.enabled():
            try:
                stored = storage_b2.save_file(file_path, "outputs")
                result = storage_b2.presigned_download(stored["object_key"])
                result.update({"success": True, "storage": "Backblaze B2",
                               "b2_object_key": stored["object_key"],
                               "file_name": Path(file_path).name})
                return result
            except Exception as exc:
                fallback = publish_artifact(file_path)
                fallback["storage_warning"] = f"B2 save failed; temporary Render link only: {exc}"
                return fallback
        return publish_artifact(file_path)
