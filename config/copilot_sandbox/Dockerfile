# GitHub Copilot CLI sandbox.
#
# This image runs the official @github/copilot CLI inside a long-lived
# container. The harness invokes `docker exec -i <container> copilot ...`
# for each session via the wrapper script `scripts/copilot-docker.sh`.
#
# Authentication is handled in-container: the harness runs `copilot login`
# on first use and the token persists in a named Docker volume mounted at
# /copilot/.copilot. GH_TOKEN / GITHUB_TOKEN is accepted as a CI fallback.

FROM node:20-bookworm-slim

ARG COPILOT_CLI_VERSION=latest
ARG UID=1000
ARG GID=1000

ENV DEBIAN_FRONTEND=noninteractive

# Playwright/Chromium runtime deps so model-driven browser tools work,
# plus a few utilities the CLI shells out to.
RUN apt-get update && apt-get install -y --no-install-recommends \
        ca-certificates curl git \
        chromium fonts-liberation \
        libnss3 libatk1.0-0 libatk-bridge2.0-0 libcups2 libxkbcommon0 \
        libxcomposite1 libxdamage1 libxrandr2 libgbm1 \
        libpango-1.0-0 libcairo2 libasound2 \
 && rm -rf /var/lib/apt/lists/*

# Match host UID/GID so writes to the bind-mounted Copilot config dir
# don't end up owned by root on Linux. The base image already has a
# `node` user at 1000:1000; rename/repoint it to the desired ids.
RUN existing_user="$(getent passwd ${UID} | cut -d: -f1 || true)"; \
    existing_group="$(getent group ${GID} | cut -d: -f1 || true)"; \
    if [ -z "$existing_group" ]; then groupadd -g ${GID} copilot; \
    elif [ "$existing_group" != "copilot" ]; then groupmod -n copilot "$existing_group"; fi; \
    if [ -z "$existing_user" ]; then \
        useradd -u ${UID} -g ${GID} -m -d /copilot -s /bin/bash copilot; \
    elif [ "$existing_user" != "copilot" ]; then \
        usermod -l copilot -d /copilot -m -g ${GID} "$existing_user"; \
    fi

# Install the official Copilot CLI globally.
RUN npm install -g @github/copilot@${COPILOT_CLI_VERSION}

# Pre-create .copilot dir with correct ownership so the named volume mount
# inherits this ownership instead of defaulting to root.
RUN mkdir -p /copilot/.copilot && chown -R copilot:copilot /copilot/.copilot

USER copilot

ENV HOME=/copilot \
    XDG_CONFIG_HOME=/copilot/.config \
    XDG_CACHE_HOME=/copilot/.cache \
    PLAYWRIGHT_BROWSERS_PATH=/copilot/.cache/ms-playwright

WORKDIR /workspace

# Long-lived idle PID 1; the harness opens sessions via `docker exec`.
CMD ["tail", "-f", "/dev/null"]
