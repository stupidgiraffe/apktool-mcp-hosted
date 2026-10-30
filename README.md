# APKTool MCP — Render-hosted

Hosted FastMCP adapter for [zinja-coder/apktool-mcp-server](https://github.com/zinja-coder/apktool-mcp-server).

## Active deployment

Render free web service: [apktool-mcp-giraffe](https://dashboard.render.com/web/srv-dbiggaek1f9s73d4fbrg). The live service URL is `https://apktool-mcp-giraffe.onrender.com`.

The remote MCP endpoint is `https://apktool-mcp-giraffe.onrender.com/private/<MCP_PATH_TOKEN>/mcp`. The private token is stored in the Render environment and must not be committed to this public repository. ChatGPT plugin authentication is set to No authentication because access is controlled by the private URL path.

### Direct ChatGPT attachment support

1. Attach an APK file in a ChatGPT conversation that has this custom MCP plugin enabled.
2. Ask ChatGPT to call `import_apk_attachment` with the attachment. The tool uses OpenAI `_meta["openai/fileParams"]` and a temporary signed file URL.
3. Pass the returned `apk_path` to `decode_apk`; inspect and modify as needed, then call `build_apk`.
4. Pass the rebuilt output path to `get_apk_download_link`. The server returns a short-lived HTTPS download URL.

File imports are limited to 120 MiB and validated as APK archives. All workspaces and URLs for built APK downloads are ephemeral. Render free services sleep after approximately **15 minutes of inactivity**, destroying temporary files. To wake, visit `https://apktool-mcp-giraffe.onrender.com/health` and re-import the APK if needed.

**Connection note:** Existing ChatGPT custom plugin installations might need a tool refresh or reconnect to discover the newly added attachment and download tools. A successful MCP tool-list response verifies the backend, not ChatGPT's client-side attachment forwarding.

### Run on Render

The deployed Python start command is `uvicorn server:app --host 0.0.0.0 --port ${PORT:-10000}`.
Runtime dependencies are in `requirements.txt`. Render environment variables include `MCP_PATH_TOKEN` (a random secret) and `PUBLIC_BASE_URL` (the HTTPS origin). Do not upload private APKs to a public GitHub repository.

### Credits

Fork-derived adaptation of [zinja-coder/apktool-mcp-server](https://github.com/zinja-coder/apktool-mcp-server), Apache 2.0. The original license is retained in `LICENSE`. Use only for APKs you own or are authorized to analyze.

---

## Historical notes (MCPHosting.io)

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

Click **Deploy**. The hosted entrypoint now exposes only the FastMCP `mcp` object and lets the provider manage the HTTP listener; it must not start a second process on port 3000. If `EADDRINUSE` persists after this commit, check provider logs or contact their support. If successful, use the dashboard's actual HTTPS `/mcp` endpoint to connect ChatGPT.

Use the single auto-discovery entrypoint `server.py`, which exports `mcp` (FastMCP). MCPHosting must start the HTTP listener itself. For local standalone development use `fastmcp run server.py --transport http --port 8000`. Running `python server.py` intentionally does not start a listener.

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
