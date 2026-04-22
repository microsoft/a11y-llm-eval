# Trivial Dockerfile so `docker compose build` (invoked by inspect_ai before
# each task) has a service to build. Without it compose emits:
#   WARN[0000] No services to build
# on every agent run. Build is a single FROM with no extra layers, so it is a
# no-op after the first cache hit and the upstream image is reused as-is.
FROM mcr.microsoft.com/playwright/python:v1.55.0-noble
