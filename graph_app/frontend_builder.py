"""
Frontend build helper and auto-watcher for Yonc Graph App.
Automatically detects available Node.js runtimes and builds or watches the frontend source.
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import threading
import time
from pathlib import Path

logger = logging.getLogger("graph_app.frontend_builder")


def find_node_executable() -> str | None:
    """Find a usable node or electron runtime on the system."""
    node = shutil.which("node")
    if node:
        return node

    # Check known cache runtimes (e.g. codex-runtimes or Antigravity)
    candidates = [
        Path.home() / ".cache" / "codex-runtimes" / "codex-primary-runtime" / "dependencies" / "node" / "bin" / "node.exe",
        Path.home() / "AppData" / "Local" / "OpenAI" / "Codex" / "bin" / "node.exe",
        Path.home() / "AppData" / "Local" / "Programs" / "Antigravity" / "Antigravity.exe",
        Path("C:/Program Files/nodejs/node.exe"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)

    return None


def build_frontend(force: bool = False) -> bool:
    """
    Builds the frontend bundle into static_v2 if sources have changed or force=True.
    Returns True if a build was performed successfully, False otherwise.
    """
    base_dir = Path(__file__).resolve().parent
    frontend_dir = base_dir / "frontend"
    src_dir = frontend_dir / "src"
    static_v2_dir = base_dir / "static_v2"
    index_html = static_v2_dir / "index.html"

    if not src_dir.exists():
        return False

    # Check if build is needed
    if not force and index_html.exists():
        index_mtime = index_html.stat().st_mtime
        watch_paths = [frontend_dir / "index.html", frontend_dir / "vite.config.ts"]
        watch_paths.extend(src_dir.rglob("*"))
        max_src_mtime = max((p.stat().st_mtime for p in watch_paths if p.is_file()), default=0)
        if max_src_mtime <= index_mtime:
            return False  # Already up to date

    node_exe = find_node_executable()
    if not node_exe:
        logger.warning("Node.js runtime not found; skipping automated frontend build.")
        return False

    vite_bin = frontend_dir / "node_modules" / "vite" / "bin" / "vite.js"
    if not vite_bin.exists():
        logger.warning("vite not found in %s; skipping build.", frontend_dir / "node_modules")
        return False

    env = os.environ.copy()
    if "Antigravity.exe" in node_exe:
        env["ELECTRON_RUN_AS_NODE"] = "1"
    else:
        node_dir = str(Path(node_exe).parent)
        env["PATH"] = f"{node_dir};{env.get('PATH', '')}"

    logger.info("Frontend source changes detected. Building static_v2 bundle with Vite...")
    try:
        proc = subprocess.run(
            [node_exe, str(vite_bin), "build"],
            cwd=str(frontend_dir),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
        )
        if proc.returncode == 0:
            logger.info("Frontend build succeeded into %s", static_v2_dir)
            return True
        else:
            logger.error("Frontend build failed:\n%s\n%s", proc.stdout, proc.stderr)
            return False
    except Exception as e:
        logger.error("Frontend build encountered error: %s", e)
        return False


def start_frontend_watcher(interval_seconds: float = 2.0) -> threading.Thread:
    """Start a lightweight background thread that checks for source changes and rebuilds."""
    def _watch():
        while True:
            try:
                time.sleep(interval_seconds)
                build_frontend(force=False)
            except Exception:
                pass

    thread = threading.Thread(target=_watch, daemon=True, name="FrontendWatcher")
    thread.start()
    return thread
