"""Bridge for invoking the Node-based Puppeteer + axe-core runner."""
import subprocess
import tempfile
import json
import os
import pathlib
import time
from typing import Optional, Dict, Any

NODE_RUNNER = pathlib.Path(__file__).resolve().parent.parent / "node_runner" / "runner.js"


def run_in_puppeteer(html: str, test_js_path: str, screenshot_path: Optional[str]) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory() as td:
        html_path = os.path.join(td, "gen.html")
        out_json = os.path.join(td, "out.json")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(html)
        args = [
            "node",
            str(NODE_RUNNER),
            html_path,
            test_js_path,
            out_json,
            screenshot_path or "",
        ]
        start = time.time()
        proc = subprocess.run(args, capture_output=True, text=True)
        duration = time.time() - start
        if proc.returncode != 0:
            return {
                "error": f"Node runner failed: {proc.stderr}",
                "duration_s": duration,
            }
        data = json.loads(open(out_json, "r", encoding="utf-8").read())
        data["duration_s"] = duration
        return data
