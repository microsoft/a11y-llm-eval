"""Bridge for invoking the Node-based Playwright + axe-core runner.

The API is intentionally small: ``run`` executes a single HTML +
test.js pair and returns a JSON-compatible dict produced by the Node script.
"""
from __future__ import annotations

import subprocess
import tempfile
import json
import os
import pathlib
import time
from typing import Optional, Dict, Any

_NODE_DIR = pathlib.Path(__file__).resolve().parent.parent / "node_runner"
PLAYWRIGHT_RUNNER = _NODE_DIR / "runner.js"


def run(html: str, test_js_path: str, screenshot_path: Optional[str]) -> Dict[str, Any]:
    if not PLAYWRIGHT_RUNNER.exists():
        return {"error": f"Runner script not found: {PLAYWRIGHT_RUNNER}", "duration_s": 0.0, "engine": "playwright"}
    with tempfile.TemporaryDirectory() as td:
        html_path = os.path.join(td, "gen.html")
        out_json = os.path.join(td, "out.json")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        args = [
            "node",
            str(PLAYWRIGHT_RUNNER),
            html_path,
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
