"""Backblaze B2 persistence for the hosted Apktool MCP.

Credentials are provided exclusively by Render environment variables.
Every stored object gets a unique name to avoid chargeable hidden versions.
"""
from __future__ import annotations

import os
import re
import secrets
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import boto3
from boto3.s3.transfer import TransferConfig
from botocore.config import Config

BASE_PREFIX = "apktool/"
SOFT_LIMIT_BYTES = 9_000_000_000
UPLOAD_LIMIT_BYTES = 512_000_000
PROJECT_LIMIT_BYTES = 2_000_000_000
PART_SIZE = 8 * 1024 * 1024
TRANSFER = TransferConfig(
    multipart_threshold=PART_SIZE,
    multipart_chunksize=PART_SIZE,
    max_concurrency=1,
    use_threads=False,
)


def enabled() -> bool:
    return all(os.environ.get(key) for key in (
        "B2_BUCKET", "B2_S3_ENDPOINT", "B2_KEY_ID", "B2_APPLICATION_KEY"
    ))


def settings():
    names = ("B2_BUCKET", "B2_S3_ENDPOINT", "B2_KEY_ID", "B2_APPLICATION_KEY")
    absent = [k for k in names if not os.environ.get(k)]
    if absent:
        raise RuntimeError("B2 not configured; set these Render environment variables: " + ", ".join(absent))
    raw_endpoint = os.environ["B2_S3_ENDPOINT"].strip().strip("'\"")
    # Accept values copied from Backblaze with no scheme, trailing slash, or a bucket path.
    if not raw_endpoint.startswith(("https://", "http://")):
        raw_endpoint = "https://" + raw_endpoint
    parsed = urlsplit(raw_endpoint)
    hostname = (parsed.hostname or "").lower()
    m = re.fullmatch(r"s3\.([a-z0-9-]+)\.backblazeb2\.com", hostname)
    if not m or parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError(
            "B2_S3_ENDPOINT must be an S3 endpoint such as "
            "https://s3.us-west-004.backblazeb2.com; "
            f"received hostname={hostname!r}. Use the S3 Endpoint field from your bucket."
        )
    endpoint = "https://" + hostname
    bucket = os.environ["B2_BUCKET"]
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{4,48}[a-zA-Z0-9]", bucket):
        raise ValueError("Invalid B2 bucket name")
    return bucket, endpoint, m.group(1)


def client():
    bucket, endpoint, region = settings()
    return boto3.client(
        "s3", endpoint_url=endpoint, region_name=region,
        aws_access_key_id=os.environ["B2_KEY_ID"],
        aws_secret_access_key=os.environ["B2_APPLICATION_KEY"],
        config=Config(signature_version="s3v4",
                      s3={"addressing_style": "path"},
                      max_pool_connections=2,
                      retries={"max_attempts": 3, "mode": "standard"},
                      connect_timeout=15, read_timeout=120),
    )


def _workspace() -> Path:
    path = Path(os.environ.get("APKTOOL_WORKSPACE", "/tmp/apktool-mcp-workspace")).resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def _local(path: str, is_dir: bool = False) -> Path:
    p = Path(path).resolve()
    if not p.is_relative_to(_workspace()) or (not p.is_dir() if is_dir else not p.is_file()):
        raise ValueError("Path must be an existing file or project inside APKTool workspace")
    return p


def _safe_key(key: str) -> str:
    if not (key.startswith(BASE_PREFIX) and
            re.fullmatch(r"[a-zA-Z0-9._/\-]+", key) and
            ".." not in key.split("/") and
            len(key) < 1000):
        raise ValueError("Invalid storage key; must be a key returned by the B2 tools")
    return key


def _inventory(s3, bucket):
    total = count = 0
    paginator = s3.get_paginator("list_objects_v2")
    for page in paginator.paginate(Bucket=bucket, Prefix=BASE_PREFIX):
        for obj in page.get("Contents", []):
            count += 1
            total += obj["Size"]
    return total, count


def status() -> dict:
    if not enabled():
        return {"configured": False,
                "missing": [k for k in ("B2_BUCKET", "B2_S3_ENDPOINT", "B2_KEY_ID", "B2_APPLICATION_KEY") if not os.environ.get(k)],
                "limit_bytes": SOFT_LIMIT_BYTES}
    bucket, _, region = settings()
    total, count = _inventory(client(), bucket)
    return {"configured": True, "bucket": bucket, "region": region,
            "prefix": BASE_PREFIX, "object_count": count,
            "used_bytes": total, "limit_bytes": SOFT_LIMIT_BYTES,
            "remaining_bytes": max(0, SOFT_LIMIT_BYTES - total),
            "note": "The ceiling applies to current objects under apktool/, not all account usage or hidden versions. Backblaze billing safeguards must be configured separately."}


def _validate_capacity(s3, bucket, size: int):
    total, _ = _inventory(s3, bucket)
    if total + size > SOFT_LIMIT_BYTES:
        raise ValueError(
            f"Apktool B2 quota would be exceeded: {total} stored bytes + {size} new bytes > {SOFT_LIMIT_BYTES}. Clean up stored files before uploading."
        )


def _object_key(kind: str, filename: str) -> str:
    if kind not in ("originals", "projects", "outputs"):
        raise ValueError("Unsupported artifact kind")
    safe_name = re.sub(r"[^a-zA-Z0-9._-]", "_", filename)[:90].strip(".") or "artifact"
    return f"{BASE_PREFIX}{kind}/{datetime.now(timezone.utc):%Y%m%dT%H%M%SZ}-{secrets.token_hex(8)}-{safe_name}"


def save_file(path: str, kind: str = "outputs") -> dict:
    file = _local(path)
    max_size = PROJECT_LIMIT_BYTES if kind == "projects" else UPLOAD_LIMIT_BYTES
    size = file.stat().st_size
    if not 0 < size <= max_size:
        raise ValueError(f"File size must be between 1 and {max_size} bytes")
    s3 = client()
    bucket, _, _ = settings()
    _validate_capacity(s3, bucket, size)
    key = _object_key(kind, file.name)
    s3.upload_file(str(file), bucket, key, ExtraArgs={"ContentType": "application/octet-stream"}, Config=TRANSFER)
    return {"saved": True, "object_key": key, "bytes": size,
            "note": "Unique object keys avoid hidden previous versions on normal uploads."}


def list_saved(limit: int = 50, kind: str = "") -> dict:
    if kind and kind not in ("originals", "projects", "outputs"):
        raise ValueError("kind must be originals, projects, outputs or empty")
    limit = max(1, min(limit, 100))
    s3 = client()
    bucket, _, _ = settings()
    prefix = BASE_PREFIX + (kind + "/" if kind else "")
    items = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=bucket, Prefix=prefix):
        for obj in page.get("Contents", []):
            items.append({"key": obj["Key"], "bytes": obj["Size"], "modified": obj["LastModified"].isoformat()})
    items.sort(key=lambda o: o["modified"], reverse=True)
    return {"items": items[:limit], "total_count": len(items),
            "note": "Call restore_saved_file or restore_project_snapshot to access older files."}


def restore_file(key: str) -> dict:
    key = _safe_key(key)
    if "/projects/" in key:
        raise ValueError("Project snapshot must be restored with restore_project_snapshot")
    s3 = client()
    bucket, _, _ = settings()
    obj = s3.head_object(Bucket=bucket, Key=key)
    if obj["ContentLength"] > UPLOAD_LIMIT_BYTES:
        raise ValueError("Stored artifact is too large for a normal file restore")
    folder = _workspace() / "restored"
    folder.mkdir(parents=True, exist_ok=True)
    name = key.rsplit("/", 1)[-1].split("-", 2)[-1]
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)[:90] or "artifact.bin"
    out = folder / (secrets.token_hex(8) + "-" + name)
    s3.download_file(bucket, key, str(out), Config=TRANSFER)
    return {"restored": True, "file_path": str(out), "bytes": out.stat().st_size}


def save_project(project_dir: str) -> dict:
    directory = _local(project_dir, is_dir=True)
    if not (directory / "apktool.yml").is_file():
        raise ValueError("Not an APKTool project (apktool.yml missing)")
    folder = _workspace() / "snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / (secrets.token_hex(10) + ".tar.gz")
    try:
        with tarfile.open(out, "w:gz", compresslevel=1, dereference=False) as archive:
            archive.add(directory, arcname=directory.name, recursive=True)
        return {**save_file(str(out), "projects"), "project": directory.name,
                "note": "Snapshot saved to B2. Restore it after Render sleeps or restarts."}
    finally:
        out.unlink(missing_ok=True)


def restore_project(key: str) -> dict:
    key = _safe_key(key)
    if not key.startswith(BASE_PREFIX + "projects/") or not key.endswith(".tar.gz"):
        raise ValueError("Not a project snapshot key")
    s3 = client()
    bucket, _, _ = settings()
    obj = s3.head_object(Bucket=bucket, Key=key)
    if obj["ContentLength"] > PROJECT_LIMIT_BYTES:
        raise ValueError("Snapshot exceeds 2 GB")
    folder = _workspace() / "snapshots"
    folder.mkdir(parents=True, exist_ok=True)
    tmp = folder / (secrets.token_hex(12) + ".tar.gz")
    destination = _workspace() / ("restored-" + secrets.token_hex(8))
    try:
        s3.download_file(bucket, key, str(tmp), Config=TRANSFER)
        with tarfile.open(tmp, "r:gz") as archive:
            members = archive.getmembers()
            total = sum(m.size for m in members if m.isfile())
            if total > 4_000_000_000 or len(members) > 250_000:
                raise ValueError("Decompressed project exceeds safety limits")
            destination.mkdir()
            archive.extractall(destination, filter="data")
        roots = [p for p in destination.iterdir() if p.is_dir() and (p / "apktool.yml").is_file()]
        if len(roots) != 1:
            raise ValueError("Snapshot does not contain exactly one APKTool project")
        return {"restored": True, "project_dir": str(roots[0]),
                "note": "Use this path with APKTool inspect, modify, and build tools."}
    finally:
        tmp.unlink(missing_ok=True)


def presigned_download(key: str, expires: int = 3600) -> dict:
    key = _safe_key(key)
    bucket, _, _ = settings()
    expires = max(60, min(int(expires), 3600))
    url = client().generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires,
        HttpMethod="GET",
    )
    return {"download_url": url, "expires_in_seconds": expires,
            "note": "Anyone possessing this temporary URL can download the private object."}



def delete_saved(key: str) -> dict:
    """Permanently remove exactly one saved key, including old B2 object versions.

    Deleting the current version alone can leave billable hidden versions.
    """
    key = _safe_key(key)
    s3 = client()
    bucket, _, _ = settings()
    versions = []
    for page in s3.get_paginator("list_object_versions").paginate(Bucket=bucket, Prefix=key):
        for field in ("Versions", "DeleteMarkers"):
            for entry in page.get(field, []):
                if entry["Key"] == key:
                    versions.append(entry["VersionId"])
    for version in versions:
        s3.delete_object(Bucket=bucket, Key=key, VersionId=version)
    return {"deleted": bool(versions), "object_key": key,
            "versions_removed": len(versions),
            "note": "All listed versions for the exact object key were removed."}


def register(mcp):
    """Expose storage management through the same ChatGPT MCP connection."""
    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
    def b2_storage_status() -> dict:
        """Check whether Backblaze B2 is configured on Render, verify bucket access, and view used space versus the 9 GB Apktool ceiling."""
        return status()

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
    def b2_list_saved(limit: int = 50, kind: str = "") -> dict:
        """List persistent APKs, outputs, and saved decoded-project snapshots; call after Render wakes to discover older work."""
        return list_saved(limit, kind)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
    def b2_save_work_file(file_path: str, kind: str = "outputs") -> dict:
        """Save a local APKTool workspace file persistently in Backblaze B2. Valid kinds: originals or outputs. Returns an object_key for later retrieval."""
        if kind not in ("originals", "outputs"):
            raise ValueError("kind must be originals or outputs")
        return save_file(file_path, kind)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
    def b2_restore_work_file(object_key: str) -> dict:
        """Restore a previously saved original or built APK from B2 into Render's temporary workspace; returns a new local file path."""
        return restore_file(object_key)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
    def b2_save_project_snapshot(project_dir: str) -> dict:
        """Save an edited/decompiled APKTool project as a compressed B2 snapshot. Call after changes and before Render's idle sleep to preserve work."""
        return save_project(project_dir)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True})
    def b2_restore_project_snapshot(object_key: str) -> dict:
        """Restore a saved project from B2, after Render restarts or sleeps, so editing and rebuild can continue with its returned project_dir."""
        return restore_project(object_key)

    @mcp.tool(annotations={"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True})
    def b2_get_saved_download_link(object_key: str) -> dict:
        """Create a one-hour HTTPS download link for a file in your private Backblaze B2 bucket; bypasses Render's ephemeral filesystem."""
        return presigned_download(object_key)

    @mcp.tool(annotations={"readOnlyHint": False, "destructiveHint": True, "openWorldHint": True})
    def b2_delete_saved_object(object_key: str) -> dict:
        """Permanently delete one saved Backblaze object and all of its versions to reclaim storage. This is irreversible; only use when the user requests deletion or cleaning up a test object."""
        return delete_saved(object_key)
