#!/usr/bin/env python3
"""Lazy, integrity-checked Apktool launcher for Python-only MCP hosting."""
import hashlib
import os
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

VERSION = "3.0.3"
SHA256 = "dbf930b076c6b9be08d57c449cacefc3bdd6b71ebd59b3066fc0e1f5b14f9423"
URLS = (
    f"https://github.com/iBotPeaches/Apktool/releases/download/v{VERSION}/apktool_{VERSION}.jar",
    f"https://bitbucket.org/iBotPeaches/apktool/downloads/apktool_{VERSION}.jar",
)

def load_jar() -> Path:
    jar = Path(os.environ.get("APKTOOL_JAR", str(Path(tempfile.gettempdir()) / "apktool-mcp-bin" / f"apktool_{VERSION}.jar")))
    if jar.is_file():
        if hashlib.sha256(jar.read_bytes()).hexdigest() == SHA256:
            return jar
        raise RuntimeError("Existing Apktool JAR SHA-256 did not match the official release.")
    jar.parent.mkdir(parents=True, exist_ok=True)
    failures = []
    for url in URLS:
        temp_path = jar.with_suffix(".download")
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "apktool-mcp-hosted/1.0"})
            with urllib.request.urlopen(request, timeout=45) as response, temp_path.open("wb") as out:
                while block := response.read(1024 * 1024):
                    out.write(block)
            if hashlib.sha256(temp_path.read_bytes()).hexdigest() != SHA256:
                raise RuntimeError("Downloaded Apktool JAR failed official SHA-256 verification.")
            temp_path.replace(jar)
            return jar
        except Exception as exc:
            failures.append(f"{url}: {exc}")
            temp_path.unlink(missing_ok=True)
    raise RuntimeError("Could not download a verified Apktool JAR: " + "; ".join(failures))

def main() -> None:
    try:
        from jdk4py import JAVA
        java = os.environ.get("APKTOOL_JAVA", str(JAVA))
        jar = load_jar()
        raise SystemExit(subprocess.call([java, "-jar", str(jar), *sys.argv[1:]]))
    except Exception as exc:
        print(f"apktool bootstrap error: {exc}", file=sys.stderr)
        raise SystemExit(1)

if __name__ == "__main__":
    main()
