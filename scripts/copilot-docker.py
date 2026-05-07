#!/usr/bin/env python3
"""Cross-platform wrapper around the Copilot CLI running inside the sandbox container.

The github-copilot-sdk launches whatever path is set as ``cli_path`` on its
SubprocessConfig and pipes JSON-RPC over the resulting process's stdio. We point
cli_path at this script so the JSON-RPC actually travels to the in-container CLI
via ``docker exec -i``.

We forward the OAuth token (and any BYOK keys) per-exec via -e so the sandbox
container can stay warm across runs without rebuilding when credentials rotate.

The container name is set by the harness (COPILOT_SANDBOX_CONTAINER) and includes
a hash of the workspace path so parallel runs don't collide.
"""

import os
import sys

_FORWARDED_VARS = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "COPILOT_GITHUB_TOKEN",
    "COPILOT_SDK_AUTH_TOKEN",
    "ANTHROPIC_API_KEY",
    "OPENAI_API_KEY",
    "AZURE_API_KEY",
    "AZURE_API_BASE",
    "AZURE_API_VERSION",
    "COPILOT_CLI_ENABLED_FEATURE_FLAGS",
    "COPILOT_FEATURE_FLAGS",
    "CHILD_CUSTOM_INSTRUCTIONS",
)


def main() -> None:
    container = os.environ.get("COPILOT_SANDBOX_CONTAINER", "a11y-copilot-sandbox")

    cmd = ["docker", "exec", "-i"]
    for var in _FORWARDED_VARS:
        value = os.environ.get(var)
        if value:
            cmd.extend(["-e", f"{var}={value}"])
    cmd.append(container)
    cmd.append("copilot")
    cmd.extend(sys.argv[1:])

    if sys.platform != "win32":
        os.execvp("docker", cmd)
    else:
        import subprocess

        proc = subprocess.run(cmd)
        sys.exit(proc.returncode)


if __name__ == "__main__":
    main()
