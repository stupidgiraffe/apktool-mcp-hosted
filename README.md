# APKTool MCP — hosted adapter

A hosting-ready adaptation of [zinja-coder/apktool-mcp-server](https://github.com/zinja-coder/apktool-mcp-server) for deployment on [MCPHosting.io](https://app.mcphosting.io/) and connection to ChatGPT.

**Status:** GitHub source prepared; cloud deployment and end-to-end operation **not yet verified**.

## MCPHosting project setup

Sign in at https://app.mcphosting.io/ and select **Projects → New project**.

| Field | Enter |
| --- | --- |
| Project name | `apktool-mcp` |
| Source | GitHub |
| Public GitHub URL | `https://github.com/stupidgiraffe/apktool-mcp-hosted` |
| Branch/tag | `main` |

Click **Deploy**. If successful, use the dashboard's actual HTTPS `/mcp` endpoint to connect ChatGPT.

Both `server.py` and `main.py` expose `mcp` (FastMCP) and `app` (ASGI). If the host requires a process start command, use `python server.py`. It serves Streamable HTTP at `/mcp` on `0.0.0.0`, using the `PORT` environment variable or port 8000.

## Runtime

- The original `apktool_mcp_server.py` code is retained with an argument-parser adjustment to support imports.
- `requirements.txt` installs FastMCP and a portable Java 21 runtime via `jdk4py`.
- On startup, a local `apktool` command shim is installed into temporary storage. On its first invocation, it downloads official Apktool 3.0.3 and verifies the publisher's SHA-256.
- Decoded APK projects are kept in temporary storage, which might disappear across requests or restarts.

## Limitations and security

The host's dependency installation, outbound download access, runtime limits, and MCP tool behavior still need testing. The original MCP tools accept **paths on the host**, not automatically APKs on your phone or attached in ChatGPT. Convenient remote APK import/export needs a separate mechanism.

Before enabling the connection, ensure your hosted MCP endpoint is protected by authentication. It exposes file inspection and modification capabilities; do not make it openly callable.

## Credits

[zinja-coder/apktool-mcp-server](https://github.com/zinja-coder/apktool-mcp-server) — Apache 2.0 license retained in `LICENSE`. [Apktool](https://apktool.org/) is separately maintained. Use only on APKs you are authorized to analyze or modify.
