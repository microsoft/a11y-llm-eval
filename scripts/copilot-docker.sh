#!/usr/bin/env bash
# Wrapper around the Copilot CLI that runs inside the sandbox container.
#
# The github-copilot-sdk launches whatever path is set as `cli_path` on
# its SubprocessConfig and pipes JSON-RPC over the resulting process's
# stdio. We point cli_path at this script so the JSON-RPC actually
# travels to the in-container CLI via `docker exec -i`.
#
# We forward the OAuth token (and any BYOK keys) per-exec via -e so the
# sandbox container can stay warm across runs without rebuilding when
# credentials rotate. GH_TOKEN / GITHUB_TOKEN is the CI/headless
# fallback; interactive users authenticate in-container via device-code
# flow (token stored in the copilot-auth Docker volume).
#
# The container name is set by the harness (COPILOT_SANDBOX_CONTAINER)
# and includes a hash of the workspace path so parallel runs don't
# collide.

set -eu

CONTAINER="${COPILOT_SANDBOX_CONTAINER:-a11y-copilot-sandbox}"

docker_exec_args=("exec" "-i")
for var in GH_TOKEN GITHUB_TOKEN COPILOT_GITHUB_TOKEN COPILOT_SDK_AUTH_TOKEN \
           ANTHROPIC_API_KEY OPENAI_API_KEY \
           AZURE_API_KEY AZURE_API_BASE AZURE_API_VERSION \
           COPILOT_CLI_ENABLED_FEATURE_FLAGS COPILOT_FEATURE_FLAGS \
           SKILLS_INSTRUCTIONS CHILD_CUSTOM_INSTRUCTIONS; do
    if [ -n "${!var:-}" ]; then
        docker_exec_args+=("-e" "${var}=${!var}")
    fi
done

exec docker "${docker_exec_args[@]}" "${CONTAINER}" copilot "$@"
