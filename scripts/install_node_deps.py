#!/usr/bin/env python3
"""Cross-platform script to install Node.js dependencies for the evaluation harness."""

import subprocess
import sys
from pathlib import Path


def main() -> int:
    node_runner_dir = Path(__file__).resolve().parent.parent / "node_runner"
    package_json = node_runner_dir / "package.json"

    if not package_json.exists():
        print("package.json missing", file=sys.stderr)
        return 1

    print(f"Installing dependencies in {node_runner_dir} ...")
    result = subprocess.run(["npm", "install"], cwd=str(node_runner_dir))
    if result.returncode != 0:
        print("npm install failed", file=sys.stderr)
        return result.returncode

    print("Installing Playwright Chromium ...")
    result = subprocess.run(["npx", "playwright", "install", "chromium"], cwd=str(node_runner_dir))
    if result.returncode != 0:
        print("npx playwright install chromium failed", file=sys.stderr)
        return result.returncode

    print("Node dependencies installed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
