"""Bridge for invoking the Node-based Playwright + axe-core runner.

The API is intentionally small: ``run`` executes a single HTML +
test.js pair and returns a JSON-compatible dict produced by the Node script.
"""
from __future__ import annotations

import contextlib
import subprocess
import tempfile
import json
import os
import pathlib
import socketserver
import threading
import time
from dataclasses import dataclass
from http.server import SimpleHTTPRequestHandler
from typing import Optional, Dict, Any

_NODE_DIR = pathlib.Path(__file__).resolve().parent.parent / "node_runner"
PLAYWRIGHT_RUNNER = _NODE_DIR / "runner.js"
SMOKE_TEST_JS = _NODE_DIR / "smoke_test.js"


def run(html: str, test_js_path: str, screenshot_path: Optional[str], html_dir: Optional[str] = None) -> Dict[str, Any]:
    if not PLAYWRIGHT_RUNNER.exists():
        return {"error": f"Runner script not found: {PLAYWRIGHT_RUNNER}", "duration_s": 0.0, "engine": "playwright"}

    # When html_dir is provided (multi-file output), write index.html there so
    # relative references (CSS/JS) resolve against a localhost static server.
    # Otherwise fall back to a disposable temp directory.
    if html_dir:
        _dir = pathlib.Path(html_dir)
        _dir.mkdir(parents=True, exist_ok=True)
        html_path = str(_dir / "index.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        with _serve_directory(_dir) as html_url:
            return _invoke_runner(html_url, test_js_path, screenshot_path, _dir)

    with tempfile.TemporaryDirectory() as td:
        html_path = os.path.join(td, "index.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        work_dir = pathlib.Path(td)
        with _serve_directory(work_dir) as html_url:
            return _invoke_runner(html_url, test_js_path, screenshot_path, work_dir)


def run_browser_smoke_eval(html: str, html_dir: Optional[str] = None) -> Dict[str, Any]:
    """Run a minimal browser smoke check and return the render evaluation payload."""
    result = run(html, str(SMOKE_TEST_JS), None, html_dir=html_dir)
    render_eval = result.get("renderEvaluation")
    if isinstance(render_eval, dict):
        return render_eval
    return {
        "rendered": False,
        "reason": "browser_smoke_eval_unavailable",
        "page_errors": [],
        "request_failures": [],
        "dom_state": {},
    }


class _ThreadingTCPServer(socketserver.ThreadingMixIn, socketserver.TCPServer):
    allow_reuse_address = True
    daemon_threads = True


class _QuietSimpleHTTPRequestHandler(SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args) -> None:  # pragma: no cover
        return


@dataclass
class StaticFileServer:
    root_dir: pathlib.Path
    host: str
    port: int
    _server: _ThreadingTCPServer
    _thread: threading.Thread

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def index_url(self) -> str:
        return f"{self.base_url}/index.html"

    def close(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=1)


def serve_directory(root_dir: pathlib.Path, host: str = "127.0.0.1", port: int = 0) -> StaticFileServer:
    handler = lambda *args, **kwargs: _QuietSimpleHTTPRequestHandler(*args, directory=str(root_dir), **kwargs)
    server = _ThreadingTCPServer((host, port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    bound_host, bound_port = server.server_address[:2]
    return StaticFileServer(
        root_dir=root_dir,
        host=str(bound_host),
        port=int(bound_port),
        _server=server,
        _thread=thread,
    )


@contextlib.contextmanager
def _serve_directory(root_dir: pathlib.Path):
    static_server = serve_directory(root_dir)
    try:
        yield static_server.index_url
    finally:
        static_server.close()


def _invoke_runner(target_url: str, test_js_path: str, screenshot_path: Optional[str], work_dir: pathlib.Path) -> Dict[str, Any]:
    out_json = str(work_dir / "out.json")
    args = [
        "node",
        str(PLAYWRIGHT_RUNNER),
        target_url,
        test_js_path,
        out_json,
        screenshot_path or "",
    ]
    start = time.time()
    proc = subprocess.run(args, capture_output=True, text=True)
    duration = time.time() - start
    if proc.returncode != 0:
        return {"error": f"Node runner failed: {proc.stderr}", "duration_s": duration, "engine": "playwright"}
    try:
        with open(out_json, "r", encoding="utf-8") as jf:
            data = json.load(jf)
    except Exception as e:
        return {"error": f"Failed reading JSON output: {e}", "duration_s": duration, "engine": "playwright"}
    data["duration_s"] = duration
    data.setdefault("engine", "playwright")
    return data
