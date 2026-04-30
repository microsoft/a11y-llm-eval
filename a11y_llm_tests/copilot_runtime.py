"""GitHub Copilot SDK-backed generation runtime.

Every generation is treated as an agentic Copilot session. The harness runs a
single long-lived ``CopilotClient`` whose CLI process lives inside a Docker
sandbox we own (``config/copilot_sandbox/``) and is reached via
``scripts/copilot-docker.py`` (``docker exec -i a11y-copilot-sandbox copilot``).

First-party Copilot authentication is provided by bind-mounting the
developer's ``~/.config/github-copilot`` directory into the container.
BYOK provider keys travel per-session in the JSON-RPC payload.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

# Imports are lazy at call sites so importing this module does not require the
# SDK to be installed (helpful for tests that monkeypatch the runtime).


# ---- Scoped permission handler -------------------------------------------


def _make_scoped_permission_handler(container_workdir: Optional[str]):
    """Return a permission callback that restricts file writes to *container_workdir*.

    The SDK calls permission handlers with signature::

        (request: PermissionRequest, invocation: dict[str, str])
            -> PermissionRequestResult | Awaitable[PermissionRequestResult]

    The handler must return a ``PermissionRequestResult`` with:
    - ``kind="approve-once"`` to allow
    - ``kind="reject"`` to deny

    Logic:
    - READ, SHELL, MCP, URL, MEMORY, HOOK, CUSTOM_TOOL → always approved.
    - WRITE → approved only if the target path is within *container_workdir*.
    - If *container_workdir* is None, returns ``PermissionHandler.approve_all``.
    """
    if not container_workdir:
        # No workdir configured → fall back to unrestricted (legacy).
        from copilot.session import PermissionHandler
        return PermissionHandler.approve_all

    # Normalize: ensure trailing slash for prefix comparison.
    prefix = container_workdir.rstrip("/") + "/"

    def _handler(request, invocation):
        from copilot.session import PermissionRequestResult

        # Only gate WRITE requests; everything else is approved.
        kind = getattr(request, "kind", None)
        kind_value = getattr(kind, "value", kind)  # handle enum or string
        if kind_value != "write":
            return PermissionRequestResult(kind="approve-once")

        # For writes, check target path from request.path or request.file_name.
        target = getattr(request, "path", None) or getattr(request, "file_name", None) or ""

        if not target:
            # Can't determine path; approve to avoid breaking legitimate writes.
            return PermissionRequestResult(kind="approve-once")

        # Resolve relative paths against the workdir (agent's cwd).
        if not target.startswith("/"):
            target = prefix + target

        # Allow only if the resolved target is within the workdir.
        if target.startswith(prefix) or target.rstrip("/") == container_workdir.rstrip("/"):
            return PermissionRequestResult(kind="approve-once")

        print(
            f"Permission DENIED: write attempted outside sandbox workdir "
            f"({target} not under {container_workdir})"
        )
        return PermissionRequestResult(kind="reject")

    return _handler
@dataclass
class AgentGenerationResult:
    """Picklable result of a single agent generation (one or many turns)."""

    html: str
    transcript: Dict[str, Any]
    usage: Dict[str, Any]
    elapsed_s: float
    sandbox: Optional[str]
    limit_error: Optional[str] = None
    session_log_path: Optional[str] = None
    # When >1, the per-turn payloads. Each entry has keys
    # ``html``, ``transcript``, ``usage``, ``elapsed_s``, ``limit_error``.
    turns: List[Dict[str, Any]] = field(default_factory=list)


def _normalize_event_type(raw: Any) -> str:
    """Coerce an SDK event type into a stable lower-dotted string.

    The SDK exposes ``event.type`` as a ``SessionEventType`` enum whose
    repr is ``SessionEventType.ASSISTANT_MESSAGE``. We normalize to
    ``"assistant.message"`` so downstream code can do plain string
    comparisons regardless of whether the value is an enum, an enum
    member's ``.value``, or already a string.
    """
    if raw is None:
        return ""
    name = getattr(raw, "name", None)
    if isinstance(name, str):
        return name.lower().replace("_", ".")
    text = str(raw)
    # Strip the enum-class prefix (e.g. ``SessionEventType.ASSISTANT_MESSAGE``).
    if text.startswith("SessionEventType."):
        text = text.split(".", 1)[1]
    return text.lower().replace("_", ".")


def _serialize_session_event(event: Any) -> Dict[str, Any]:
    """Best-effort dump of a CopilotSession event for transcript storage.

    Result is guaranteed JSON-clean: any non-serializable value (SDK
    dataclasses like ``CustomAgentsUpdatedAgent``, enums, datetimes) is
    coerced via ``str()`` so callers can ``json.dumps(...)`` without
    ``default=str``.
    """
    payload: Dict[str, Any] = {"type": _normalize_event_type(getattr(event, "type", None))}
    data = getattr(event, "data", None)
    if data is None:
        return payload

    raw_data: Any = None
    # Pydantic v2 model
    dump = getattr(data, "model_dump", None)
    if callable(dump):
        try:
            raw_data = dump(mode="json")
        except Exception:
            raw_data = None
    if raw_data is None:
        if isinstance(data, dict):
            raw_data = data
        else:
            raw_data = {
                k: getattr(data, k)
                for k in dir(data)
                if not k.startswith("_") and not callable(getattr(data, k, None))
            }

    # Round-trip through json with ``default=str`` so any leftover
    # non-JSON objects (SDK dataclasses, enums, datetimes) become strings
    # before downstream writers (which use plain ``json.dumps``) see them.
    try:
        payload["data"] = json.loads(json.dumps(raw_data, default=str))
    except Exception:
        payload["data"] = json.loads(json.dumps(str(raw_data)))
    return payload


def _aggregate_usage(events: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Sum up token usage from assistant.usage / assistant.turn_end events."""
    tokens_in = 0
    tokens_out = 0
    total = 0
    saw_usage = False
    for ev in events:
        if (ev.get("type") or "") not in {"assistant.usage", "assistant.turn.end"}:
            continue
        data = ev.get("data") or {}
        if not isinstance(data, dict):
            continue
        usage = data.get("usage") if isinstance(data.get("usage"), dict) else data
        ti = usage.get("input_tokens") or usage.get("prompt_tokens")
        to = usage.get("output_tokens") or usage.get("completion_tokens")
        tt = usage.get("total_tokens")
        if ti is None and to is None and tt is None:
            continue
        saw_usage = True
        if isinstance(ti, (int, float)):
            tokens_in += int(ti)
        if isinstance(to, (int, float)):
            tokens_out += int(to)
        if isinstance(tt, (int, float)):
            total += int(tt)
    if not saw_usage:
        return {}
    return {
        "prompt_tokens": tokens_in or None,
        "completion_tokens": tokens_out or None,
        "total_tokens": total or (tokens_in + tokens_out) or None,
    }


def _last_assistant_message(events: List[Dict[str, Any]]) -> str:
    for ev in reversed(events):
        if ev.get("type") == "assistant.message":
            data = ev.get("data") or {}
            if isinstance(data, dict):
                content = data.get("content")
                if isinstance(content, str):
                    return content
    return ""


class _StreamingSessionLog:
    """Append session events to ``copilot_logs/session-<id>.jsonl`` as they arrive.

    The session id isn't known until ``create_session`` returns, but events
    can start arriving before that. We buffer the first events to a temp
    file, then rename it once ``bind_session_id`` is called. Each ``write``
    flushes to disk so ``tail -f`` sees progress in real time.
    """

    def __init__(self, log_dir: Optional[Path]) -> None:
        self._log_dir = log_dir
        self._handle: Optional[Any] = None
        self._path: Optional[Path] = None
        self._session_id: Optional[str] = None
        if log_dir is not None:
            try:
                log_dir.mkdir(parents=True, exist_ok=True)
                self._path = log_dir / f"session-pending-{os.getpid()}-{id(self)}.jsonl"
                self._handle = self._path.open("w", encoding="utf-8")
            except OSError:
                self._handle = None
                self._path = None

    def write(self, event: Dict[str, Any]) -> None:
        if self._handle is None:
            return
        try:
            self._handle.write(json.dumps(event, default=str) + "\n")
            self._handle.flush()
        except Exception:
            pass

    def bind_session_id(self, session_id: str) -> None:
        if self._handle is None or self._log_dir is None or self._session_id == session_id:
            return
        self._session_id = session_id
        target = self._log_dir / f"session-{session_id}.jsonl"
        try:
            self._handle.flush()
            if self._path is not None and self._path != target:
                # Move the in-flight log to its final name; subsequent writes
                # continue to flow through the same handle.
                try:
                    self._path.rename(target)
                except OSError:
                    # Cross-device or pre-existing target: copy contents and
                    # reopen on the target path in append mode.
                    contents = self._path.read_text(encoding="utf-8") if self._path.exists() else ""
                    target.write_text(contents, encoding="utf-8")
                    try:
                        self._path.unlink()
                    except OSError:
                        pass
                    self._handle.close()
                    self._handle = target.open("a", encoding="utf-8")
                self._path = target
        except Exception:
            pass

    def close(self) -> None:
        if self._handle is not None:
            try:
                self._handle.flush()
                self._handle.close()
            except Exception:
                pass
            self._handle = None

    @property
    def path(self) -> Optional[str]:
        return str(self._path) if self._path else None


class CopilotRuntime:
    """Async wrapper around ``copilot.CopilotClient`` running inside Docker.

    Lifecycle:
        runtime = CopilotRuntime(log_dir=..., workspace_dir=...)
        await runtime.start()
        result = await runtime.generate_agent(...)
        await runtime.stop()
    """

    # Module-level paths discovered relative to the package install location.
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    _COMPOSE_FILE = _REPO_ROOT / "config" / "copilot_sandbox" / "compose.yaml"
    _DOCKERFILE = _REPO_ROOT / "config" / "copilot_sandbox" / "Dockerfile"
    _IMAGE_HASH_SIDECAR = _REPO_ROOT / "config" / "copilot_sandbox" / ".image-hash"
    _IMAGE_TAG = "a11y-eval/copilot-sandbox:latest"
    _WRAPPER_SCRIPT = _REPO_ROOT / "scripts" / "copilot-docker.py"
    _CONTAINER_WORKSPACE = "/workspace"

    def __init__(
        self,
        log_dir: Optional[str] = None,
        *,
        workspace_dir: Optional[str] = None,
    ) -> None:
        self._log_dir: Optional[Path] = Path(log_dir) if log_dir else None
        if self._log_dir:
            self._log_dir.mkdir(parents=True, exist_ok=True)
        self._client: Any = None
        self._lock = asyncio.Lock()
        ws = workspace_dir or os.environ.get("COPILOT_WORKSPACE") or os.getcwd()
        self._workspace_dir: Path = Path(ws).expanduser().resolve()
        # Derive a unique container name from the workspace path so two
        # harness instances on the same Docker host don't collide.
        ws_hash = hashlib.sha256(str(self._workspace_dir).encode()).hexdigest()[:8]
        self._container_name: str = f"a11y-copilot-sandbox-{ws_hash}"
        self._preflight_done: bool = False

    async def preflight(self) -> None:
        """Bring the sandbox container up and ensure auth (idempotent).

        The CLI should call this once before the generation loop so that the
        (potentially interactive) device-code login happens in the user's
        foreground terminal, not deep inside a concurrent worker.
        """
        if self._preflight_done:
            return
        self._ensure_dependencies()
        await asyncio.to_thread(self._compose_up)
        await asyncio.to_thread(self._wait_for_container)
        await asyncio.to_thread(self._ensure_container_auth)
        self._preflight_done = True

    async def start(self) -> None:
        """Bring the sandbox container up (idempotent), then start the SDK client."""
        from copilot import CopilotClient, SubprocessConfig

        async with self._lock:
            if self._client is not None:
                return

            # If the CLI didn't call preflight() explicitly, do it now.
            await self.preflight()

            env = dict(os.environ)
            env["COPILOT_SANDBOX_CONTAINER"] = self._container_name

            # If a GitHub token is available in the environment, pass it to
            # the SDK so the CLI receives it via --auth-token-env. The wrapper
            # script forwards COPILOT_SDK_AUTH_TOKEN to the container.
            github_token = (
                os.environ.get("COPILOT_GITHUB_TOKEN")
                or os.environ.get("GH_TOKEN")
                or os.environ.get("GITHUB_TOKEN")
            )

            config = SubprocessConfig(
                cli_path=sys.executable,
                cli_args=[str(self._WRAPPER_SCRIPT)],
                env=env,
                use_logged_in_user=True,
                **({"github_token": github_token} if github_token else {}),
            )
            self._client = CopilotClient(config)
            await self._client.start()

    async def stop(self) -> None:
        if self._client is not None:
            try:
                await self._client.stop()
            finally:
                self._client = None
        # Leave the container warm so subsequent harness invocations skip the
        # image build. Operators can stop it with:
        #   docker compose -f config/copilot_sandbox/compose.yaml down

    # ---- Docker compose lifecycle -----------------------------------

    @classmethod
    def _ensure_dependencies(cls) -> None:
        if shutil.which("docker") is None:
            raise RuntimeError(
                "docker is required: the harness runs the GitHub Copilot CLI "
                "inside a sandbox container."
            )
        if not cls._COMPOSE_FILE.exists():
            raise RuntimeError(f"Compose file not found: {cls._COMPOSE_FILE}")
        if not cls._WRAPPER_SCRIPT.exists():
            raise RuntimeError(f"Wrapper script not found: {cls._WRAPPER_SCRIPT}")

    def _ensure_container_auth(self) -> None:
        """Verify the in-container CLI is authenticated.

        Resolution order:
        1. ``GH_TOKEN`` / ``GITHUB_TOKEN`` / ``COPILOT_GITHUB_TOKEN`` env var
        2. ``gh auth token`` on the host (GitHub CLI)
        3. Raise with instructions to install gh or set a token manually.
        """
        # Fix ownership of the copilot-auth volume mount — it may have been
        # created by root on the first container start (Docker volume init).
        self._fix_copilot_dir_ownership()

        if (
            os.environ.get("GH_TOKEN")
            or os.environ.get("GITHUB_TOKEN")
            or os.environ.get("COPILOT_GITHUB_TOKEN")
        ):
            return

        # Try the GitHub CLI as a token source (works when user has run
        # `gh auth login` on the host).
        gh_token = self._try_gh_auth_token()
        if gh_token:
            os.environ["GITHUB_TOKEN"] = gh_token
            return

        raise RuntimeError(
            "No GitHub token available for the Copilot sandbox.\n"
            "\n"
            "Authenticate using one of the following methods:\n"
            "\n"
            "  1. Install the GitHub CLI and log in:\n"
            "       brew install gh\n"
            "       gh auth login\n"
            "\n"
            "  2. Set a token environment variable:\n"
            "       export GITHUB_TOKEN=<your-token>\n"
            "\n"
            "     Any of GH_TOKEN, GITHUB_TOKEN, or COPILOT_GITHUB_TOKEN will work.\n"
            "     A fine-grained PAT with Copilot access is recommended for CI."
        )

    def _try_gh_auth_token(self) -> Optional[str]:
        """Try to get a GitHub token from the ``gh`` CLI on the host."""
        gh = shutil.which("gh")
        if not gh:
            return None
        try:
            result = subprocess.run(
                [gh, "auth", "token"],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode == 0:
                token = result.stdout.strip()
                if token:
                    return token
        except (OSError, subprocess.TimeoutExpired):
            pass
        return None

    def _fix_copilot_dir_ownership(self) -> None:
        """Ensure /copilot/.copilot is owned by the container user.

        Docker named volumes are initialized with root ownership. If the
        copilot user can't write there, the CLI silently fails (exit 1,
        no output). Fix it once at startup.
        """
        try:
            subprocess.run(
                [
                    "docker", "exec", "-u", "root", self._container_name,
                    "bash", "-c",
                    "mkdir -p /copilot/.copilot && chown -R copilot:copilot /copilot/.copilot",
                ],
                capture_output=True, timeout=10,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _compose_env(self) -> Dict[str, str]:
        env = dict(os.environ)
        env.setdefault("COPILOT_WORKSPACE", str(self._workspace_dir))
        env["COPILOT_CONTAINER_NAME"] = self._container_name
        try:
            env.setdefault("COPILOT_UID", str(os.getuid()))
            env.setdefault("COPILOT_GID", str(os.getgid()))
        except AttributeError:
            # Windows: leave defaults from compose.yaml.
            pass
        return env

    def _compose_up(self) -> None:
        env = self._compose_env()

        # Compute hash of build inputs to decide whether to rebuild.
        current_hash = self._compute_build_hash()
        force_rebuild = bool(env.get("COPILOT_SANDBOX_REBUILD"))
        cached_hash = self._read_cached_hash()
        image_present = self._image_exists(self._IMAGE_TAG)
        hash_matches = (cached_hash == current_hash) and image_present

        # Fast path: container already running with the up-to-date image. The
        # common case after the first build — no docker compose call at all.
        if (
            not force_rebuild
            and hash_matches
            and self._container_is_running()
            and self._container_uses_current_image()
        ):
            return

        # If the container is running but stale (Dockerfile changed since it
        # was created), tear it down so the rebuild takes effect.
        if force_rebuild or (
            self._container_is_running() and not self._container_uses_current_image()
        ):
            subprocess.run(
                ["docker", "rm", "-f", self._container_name],
                capture_output=True, text=True,
            )

        # Pre-emptively remove any stopped/orphaned container holding the
        # canonical name so ``compose up`` cannot hit ``Conflict. The container
        # name ... is already in use``. ``rm -f`` is a silent no-op when
        # nothing matches.
        subprocess.run(
            ["docker", "rm", "-f", self._container_name],
            capture_output=True, text=True,
        )

        cmd = [
            "docker", "compose",
            "-f", str(self._COMPOSE_FILE),
            "up", "-d",
        ]
        # Only pass --build when the build inputs actually changed (or the
        # image is missing / a rebuild was forced). This avoids a 5-15s
        # metadata roundtrip on every harness start.
        if force_rebuild or not hash_matches:
            cmd.append("--build")
        result = subprocess.run(cmd, env=env, capture_output=True, text=True)
        if result.returncode != 0:
            raise RuntimeError(
                f"`docker compose up` failed (exit {result.returncode}):\n"
                f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
            )

        # Persist the hash so the next start can take the fast path.
        if force_rebuild or not hash_matches:
            self._write_cached_hash(current_hash)

    @classmethod
    def _compute_build_hash(cls) -> str:
        """Hash the inputs that should trigger a rebuild.

        Includes the Dockerfile and compose.yaml; if either changes the
        next harness start performs a fresh build, otherwise the cached
        image is reused as-is.
        """
        h = hashlib.sha256()
        for path in (cls._DOCKERFILE, cls._COMPOSE_FILE):
            try:
                h.update(path.read_bytes())
            except OSError:
                # Missing file makes the hash unstable on purpose so we
                # bias toward rebuilding rather than reusing a stale image.
                h.update(b"\x00missing\x00")
        return h.hexdigest()[:16]

    @classmethod
    def _read_cached_hash(cls) -> Optional[str]:
        try:
            return cls._IMAGE_HASH_SIDECAR.read_text().strip() or None
        except OSError:
            return None

    @classmethod
    def _write_cached_hash(cls, value: str) -> None:
        try:
            cls._IMAGE_HASH_SIDECAR.parent.mkdir(parents=True, exist_ok=True)
            cls._IMAGE_HASH_SIDECAR.write_text(value + "\n")
        except OSError:
            # Non-fatal: missing sidecar just means we'll rebuild next run.
            pass

    @classmethod
    def _image_exists(cls, tag: str) -> bool:
        probe = subprocess.run(
            ["docker", "image", "inspect", tag],
            capture_output=True, text=True,
        )
        return probe.returncode == 0

    def _container_uses_current_image(self) -> bool:
        """Return True if the running container is built from the current
        ``a11y-eval/copilot-sandbox:latest`` image (i.e. not stale after a
        rebuild)."""
        container_image = subprocess.run(
            ["docker", "inspect", "-f", "{{.Image}}", self._container_name],
            capture_output=True, text=True,
        )
        if container_image.returncode != 0:
            return False
        image_id = subprocess.run(
            ["docker", "image", "inspect", "-f", "{{.Id}}", self._IMAGE_TAG],
            capture_output=True, text=True,
        )
        if image_id.returncode != 0:
            return False
        return container_image.stdout.strip() == image_id.stdout.strip()

    def _container_is_running(self) -> bool:
        probe = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", self._container_name],
            capture_output=True, text=True,
        )
        return probe.returncode == 0 and probe.stdout.strip() == "true"

    def _wait_for_container(self, timeout_s: float = 30.0) -> None:
        deadline = time.monotonic() + timeout_s
        last_err: Optional[str] = None
        while time.monotonic() < deadline:
            probe = subprocess.run(
                ["docker", "exec", self._container_name, "copilot", "--version"],
                capture_output=True, text=True,
            )
            if probe.returncode == 0:
                return
            last_err = probe.stderr.strip() or probe.stdout.strip()
            time.sleep(0.5)
        raise RuntimeError(
            f"Copilot sandbox container did not become ready within {timeout_s}s. "
            f"Last error: {last_err}"
        )

    # ---- path translation -------------------------------------------

    def host_path_to_container(self, host_path: str) -> str:
        """Translate an absolute host path into a container-side path.

        Paths inside the workspace are remapped onto ``/workspace/...``;
        anything outside the workspace raises so the harness can fail loudly
        rather than handing the SDK a path the in-container CLI cannot see.
        """
        resolved = Path(host_path).resolve()
        try:
            rel = resolved.relative_to(self._workspace_dir)
        except ValueError as exc:
            raise RuntimeError(
                f"Path {resolved} is outside the workspace {self._workspace_dir}; "
                "move it into the workspace or extend compose.yaml with an "
                "additional bind mount."
            ) from exc
        return f"{self._CONTAINER_WORKSPACE}/{rel.as_posix()}"

    @property
    def sandbox_label(self) -> str:
        return f"docker:{self._COMPOSE_FILE.relative_to(self._REPO_ROOT).as_posix()}"

    def _write_session_log(self, session_id: str, events: List[Dict[str, Any]]) -> Optional[str]:
        """Write the full event list at session end.

        ``_StreamingSessionLog`` already streams each event as it arrives, so
        this method now only re-writes the file when a streaming writer was
        not used (e.g. tests that don't go through ``on_event``). It is kept
        for backwards compatibility with the existing call sites.
        """
        if self._log_dir is None:
            return None
        path = self._log_dir / f"session-{session_id}.jsonl"
        if path.exists():
            return str(path)
        try:
            with path.open("w", encoding="utf-8") as handle:
                for ev in events:
                    handle.write(json.dumps(ev, default=str) + "\n")
        except Exception:
            return None
        return str(path)

    def _open_streaming_log(self) -> "_StreamingSessionLog":
        return _StreamingSessionLog(self._log_dir)

    # Filename the agent is instructed to write its final HTML to inside its
    # per-session working directory. Stable so the user prompt embedding the
    # filename stays cache-key-stable across runs.
    OUTPUT_FILENAME = "index.html"

    @staticmethod
    def _read_workdir_artifact(workdir: Optional[Path]) -> Optional[str]:
        """Return the content of ``<workdir>/index.html`` if present.

        Returns ``None`` when no workdir was configured, the file does not
        exist, or it cannot be decoded. Empty files return ``None`` so the
        caller can fall back to message-based extraction.
        """
        if workdir is None:
            return None
        target = workdir / CopilotRuntime.OUTPUT_FILENAME
        try:
            if not target.is_file():
                return None
            text = target.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            return None
        return text or None

    async def _run_single(
        self,
        *,
        model: str,
        user_prompt: str,
        provider_config: Optional[Dict[str, Any]] = None,
        skill_directories: Optional[List[str]] = None,
        excluded_tools: Optional[List[str]] = None,
        timeout_s: float = 600.0,
        seed_messages: Optional[List[Dict[str, str]]] = None,
        working_directory: Optional[str] = None,
    ) -> AgentGenerationResult:
        """Run a single agent generation, returning HTML + transcript.

        ``seed_messages`` is a list of ``{role, content}`` dicts. For multi-turn
        runs, the runtime opens one session and replays prior turns by sending
        them in order before the final ``user_prompt``. Each prior turn is
        treated as a separate user message; the SDK retains full history within
        the session so the model sees the conversation context naturally.

        The runtime does NOT customise the SDK's system message. The harness
        appends any output-format / disk-write instructions onto the
        ``user_prompt`` itself at the generator layer, which keeps the SDK's
        default agent system prompt (and its tool-use priming) intact.
        """
        from copilot.session import PermissionHandler

        if self._client is None:
            await self.start()

        host_workdir: Optional[Path] = None
        container_workdir: Optional[str] = None
        if working_directory:
            host_workdir = Path(working_directory).expanduser().resolve()
            host_workdir.mkdir(parents=True, exist_ok=True)
            container_workdir = self.host_path_to_container(str(host_workdir))

        # Use a scoped handler that restricts file writes to the sandbox workdir.
        # Falls back to approve_all when no workdir is configured.
        permission_handler = _make_scoped_permission_handler(container_workdir)

        kwargs: Dict[str, Any] = {
            "on_permission_request": permission_handler,
            "model": model,
        }
        if container_workdir is not None:
            kwargs["working_directory"] = container_workdir
        if provider_config:
            # Pass through BYOK config verbatim. SDK validates fields.
            provider_payload = self._build_provider_payload(provider_config)
            if provider_payload:
                kwargs["provider"] = provider_payload
        if skill_directories:
            kwargs["skill_directories"] = [
                self.host_path_to_container(p) for p in skill_directories
            ]
        if excluded_tools:
            kwargs["excluded_tools"] = list(excluded_tools)

        events: List[Dict[str, Any]] = []
        idle_event = asyncio.Event()
        error_holder: Dict[str, Any] = {}
        stream = self._open_streaming_log()

        def on_event(event: Any) -> None:
            payload = _serialize_session_event(event)
            events.append(payload)
            stream.write(payload)
            etype = payload.get("type") or ""
            if etype == "session.idle":
                idle_event.set()
            elif etype == "session.error":
                data = payload.get("data") or {}
                if isinstance(data, dict):
                    error_holder["message"] = data.get("message") or data.get("error") or "session.error"
                idle_event.set()

        kwargs["on_event"] = on_event

        start = time.monotonic()
        async with await self._client.create_session(**kwargs) as session:
            session_id = getattr(session, "session_id", "unknown")
            stream.bind_session_id(str(session_id))

            # Replay any prior turns (multi-turn skill flow). Each replay must
            # complete (its own session.idle) before we send the next.
            if seed_messages:
                for prior in seed_messages:
                    role = (prior.get("role") or "user").lower()
                    if role != "user":
                        # Only user turns are re-sent; assistant turns stay in
                        # the session's own conversation history.
                        continue
                    idle_event.clear()
                    await session.send(prior.get("content") or "")
                    try:
                        await asyncio.wait_for(idle_event.wait(), timeout=timeout_s)
                    except asyncio.TimeoutError:
                        error_holder["message"] = f"timeout waiting for replay turn (session={session_id})"
                        break

            if "message" not in error_holder:
                idle_event.clear()
                await session.send(user_prompt)
                try:
                    await asyncio.wait_for(idle_event.wait(), timeout=timeout_s)
                except asyncio.TimeoutError:
                    error_holder["message"] = f"timeout waiting for assistant message (session={session_id})"

        elapsed = time.monotonic() - start
        # Prefer the artifact the agent wrote to disk; fall back to the last
        # assistant message when the agent didn't (or couldn't) write a file.
        disk_html = self._read_workdir_artifact(host_workdir)
        if disk_html:
            html = disk_html
            output_source = "disk"
        else:
            html = _last_assistant_message(events)
            output_source = "message"
        usage = _aggregate_usage(events)
        stream.close()
        log_path = stream.path or self._write_session_log(str(session_id), events)
        transcript = {
            "format": "copilot_agent_conversation/v1",
            "session_id": str(session_id),
            "events": events,
            "output_source": output_source,
            "working_directory": str(host_workdir) if host_workdir else None,
        }
        return AgentGenerationResult(
            html=html,
            transcript=transcript,
            usage=usage,
            elapsed_s=elapsed,
            sandbox=self.sandbox_label,
            limit_error=error_holder.get("message"),
            session_log_path=log_path,
        )

    async def generate_agent(
        self,
        *,
        model: str,
        user_prompt: str,
        provider_config: Optional[Dict[str, Any]] = None,
        skill_directories: Optional[List[str]] = None,
        excluded_tools: Optional[List[str]] = None,
        timeout_s: float = 600.0,
        working_directory: Optional[str] = None,
    ) -> AgentGenerationResult:
        return await self._run_single(
            model=model,
            user_prompt=user_prompt,
            provider_config=provider_config,
            skill_directories=skill_directories,
            excluded_tools=excluded_tools,
            timeout_s=timeout_s,
            working_directory=working_directory,
        )

    async def generate_skill_multi_turn(
        self,
        *,
        model: str,
        rendered_turn_prompts: List[str],
        skill_dir_abs_path: str,
        skill_id: str,
        provider_config: Optional[Dict[str, Any]] = None,
        excluded_tools: Optional[List[str]] = None,
        timeout_s: float = 600.0,
        working_directory: Optional[str] = None,
    ) -> AgentGenerationResult:
        """Run a skill's ordered turn prompts on a single session.

        Returns a single ``AgentGenerationResult`` whose ``turns`` list carries
        one entry per turn (in input order). The top-level fields capture the
        FINAL turn's html/usage; callers that need per-turn data should use
        ``turns``.

        ``skill_dir_abs_path`` is the host-side path to the specific skill
        directory (e.g. ``config/skills/building-accessible-ui``). The SDK's
        ``skill_directories`` parameter expects the **parent** so it can
        discover ``SKILL.md`` files in immediate subdirectories.
        Output-format instructions are appended to each turn's user prompt
        at the generator layer.
        """
        from copilot.session import PermissionHandler

        if self._client is None:
            await self.start()
        if not rendered_turn_prompts:
            raise ValueError("rendered_turn_prompts must be non-empty")

        host_workdir: Optional[Path] = None
        container_workdir: Optional[str] = None
        if working_directory:
            host_workdir = Path(working_directory).expanduser().resolve()
            host_workdir.mkdir(parents=True, exist_ok=True)
            container_workdir = self.host_path_to_container(str(host_workdir))

        skill_parent_dir = str(Path(skill_dir_abs_path).parent)
        container_skill_parent = self.host_path_to_container(skill_parent_dir)

        # Scoped handler: restrict file writes to the sandbox workdir.
        permission_handler = _make_scoped_permission_handler(container_workdir)

        kwargs: Dict[str, Any] = {
            "on_permission_request": permission_handler,
            "model": model,
            "skill_directories": [container_skill_parent],
        }
        if container_workdir is not None:
            kwargs["working_directory"] = container_workdir
        if provider_config:
            payload = self._build_provider_payload(provider_config)
            if payload:
                kwargs["provider"] = payload
        if excluded_tools:
            kwargs["excluded_tools"] = list(excluded_tools)

        events: List[Dict[str, Any]] = []
        idle_event = asyncio.Event()
        error_holder: Dict[str, Any] = {}
        stream = self._open_streaming_log()

        def on_event(event: Any) -> None:
            payload = _serialize_session_event(event)
            events.append(payload)
            stream.write(payload)
            etype = payload.get("type") or ""
            if etype == "session.idle":
                idle_event.set()
            elif etype == "session.error":
                data = payload.get("data") or {}
                if isinstance(data, dict):
                    error_holder["message"] = data.get("message") or data.get("error") or "session.error"
                idle_event.set()

        kwargs["on_event"] = on_event

        per_turn_records: List[Dict[str, Any]] = []
        total_start = time.monotonic()

        async with await self._client.create_session(**kwargs) as session:
            session_id = getattr(session, "session_id", "unknown")
            stream.bind_session_id(str(session_id))

            for turn_index, prompt in enumerate(rendered_turn_prompts):
                if "message" in error_holder:
                    per_turn_records.append({
                        "turn_index": turn_index,
                        "html": "",
                        "transcript": {
                            "format": "copilot_agent_conversation/v1",
                            "turn_index": turn_index,
                            "skipped": True,
                            "skip_reason": error_holder["message"],
                        },
                        "usage": {},
                        "elapsed_s": 0.0,
                        "limit_error": error_holder["message"],
                    })
                    continue

                pre_event_count = len(events)
                idle_event.clear()
                turn_start = time.monotonic()
                await session.send(prompt)
                try:
                    await asyncio.wait_for(idle_event.wait(), timeout=timeout_s)
                except asyncio.TimeoutError:
                    error_holder["message"] = f"timeout on turn {turn_index} (session={session_id})"

                turn_events = events[pre_event_count:]
                disk_html = self._read_workdir_artifact(host_workdir)
                if disk_html:
                    turn_html = disk_html
                    turn_output_source = "disk"
                else:
                    turn_html = _last_assistant_message(turn_events)
                    turn_output_source = "message"
                turn_usage = _aggregate_usage(turn_events)
                per_turn_records.append({
                    "turn_index": turn_index,
                    "html": turn_html,
                    "transcript": {
                        "format": "copilot_agent_conversation/v1",
                        "turn_index": turn_index,
                        "events": turn_events,
                        "output_source": turn_output_source,
                        "working_directory": str(host_workdir) if host_workdir else None,
                    },
                    "usage": turn_usage,
                    "elapsed_s": time.monotonic() - turn_start,
                    "limit_error": error_holder.get("message"),
                })

        elapsed_total = time.monotonic() - total_start
        stream.close()
        log_path = stream.path or self._write_session_log(str(session_id), events)
        final_turn = per_turn_records[-1] if per_turn_records else {"html": "", "usage": {}}
        return AgentGenerationResult(
            html=final_turn.get("html") or "",
            transcript={
                "format": "copilot_agent_conversation/v1",
                "session_id": str(session_id),
                "turns": [
                    {"turn_index": r["turn_index"], "events": r["transcript"].get("events", [])}
                    for r in per_turn_records
                ],
            },
            usage=final_turn.get("usage") or {},
            elapsed_s=elapsed_total,
            sandbox=self.sandbox_label,
            limit_error=error_holder.get("message"),
            session_log_path=log_path,
            turns=per_turn_records,
        )

    @staticmethod
    def _build_provider_payload(provider_config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Translate harness ``provider_config`` into SDK ``ProviderConfig`` dict.

        Only BYOK fields supported by the SDK are forwarded. Returns ``None``
        when the config does not request BYOK routing (i.e. no ``type`` or
        ``base_url``).
        """
        if not isinstance(provider_config, dict):
            return None
        ptype = provider_config.get("type")
        base_url = provider_config.get("base_url")
        if not ptype and not base_url:
            return None
        payload: Dict[str, Any] = {}
        for key in ("type", "base_url", "api_key", "bearer_token", "wire_api"):
            value = provider_config.get(key)
            if value is not None:
                payload[key] = value
        # Pull api_key from env when configured by name only.
        api_key_env = provider_config.get("api_key_env")
        if "api_key" not in payload and isinstance(api_key_env, str):
            env_value = os.environ.get(api_key_env)
            if env_value:
                payload["api_key"] = env_value
        azure_cfg = provider_config.get("azure")
        if isinstance(azure_cfg, dict):
            payload["azure"] = dict(azure_cfg)
        return payload or None


# ---- Synchronous helpers used by the (still sync) generator API ----


_default_runtime: Optional[CopilotRuntime] = None
_runtime_loop: Optional[asyncio.AbstractEventLoop] = None
_runtime_thread: Optional[threading.Thread] = None
_runtime_lock = threading.Lock()


def _ensure_runtime_loop() -> asyncio.AbstractEventLoop:
    """Return a long-lived event loop running in a background thread.

    The Copilot SDK ``CopilotClient`` binds its background reader task and
    response futures to whatever loop ``client.start()`` runs on. Each
    ``asyncio.run`` call creates a fresh loop, which would invalidate the
    cached client on the second sync call ("Future attached to a different
    loop"). We avoid that by pinning every runtime call to a single
    persistent loop and using ``run_coroutine_threadsafe`` to drive it from
    sync callers.
    """
    global _runtime_loop, _runtime_thread
    with _runtime_lock:
        if _runtime_loop is not None and _runtime_loop.is_running():
            return _runtime_loop
        ready = threading.Event()

        def _run() -> None:
            global _runtime_loop
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            _runtime_loop = loop
            ready.set()
            try:
                loop.run_forever()
            finally:
                loop.close()

        _runtime_thread = threading.Thread(
            target=_run, name="copilot-runtime-loop", daemon=True
        )
        _runtime_thread.start()
        ready.wait()
        assert _runtime_loop is not None
        return _runtime_loop


def _run_on_runtime_loop(coro: Any) -> Any:
    loop = _ensure_runtime_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result()


def get_default_runtime(log_dir: Optional[str] = None) -> CopilotRuntime:
    """Return a process-wide default runtime, creating it if needed.

    The runtime is started lazily on the first ``run_*`` call. Callers that
    want full lifecycle control should construct ``CopilotRuntime`` directly.
    """
    global _default_runtime
    if _default_runtime is None:
        _default_runtime = CopilotRuntime(log_dir=log_dir)
    elif log_dir is not None:
        _default_runtime._log_dir = Path(log_dir)
        _default_runtime._log_dir.mkdir(parents=True, exist_ok=True)
    return _default_runtime


def preflight_default_runtime_sync(log_dir: Optional[str] = None) -> None:
    """Run the container preflight (compose-up + auth) synchronously.

    The CLI calls this once before the generation loop so that any
    interactive auth prompts happen in the user's foreground terminal
    rather than deep inside a concurrent worker.
    """
    runtime = get_default_runtime(log_dir=log_dir)
    _run_on_runtime_loop(runtime.preflight())


def run_agent_generation_sync(
    *,
    model: str,
    user_prompt: str,
    provider_config: Optional[Dict[str, Any]] = None,
    skill_directories: Optional[List[str]] = None,
    excluded_tools: Optional[List[str]] = None,
    timeout_s: float = 600.0,
    log_dir: Optional[str] = None,
    working_directory: Optional[str] = None,
) -> AgentGenerationResult:
    """Synchronous entry point used by ``generator.generate_html_with_agent_meta``."""
    runtime = get_default_runtime(log_dir=log_dir)

    async def _go() -> AgentGenerationResult:
        await runtime.start()
        return await runtime.generate_agent(
            model=model,
            user_prompt=user_prompt,
            provider_config=provider_config,
            skill_directories=skill_directories,
            excluded_tools=excluded_tools,
            timeout_s=timeout_s,
            working_directory=working_directory,
        )

    return _run_on_runtime_loop(_go())


def run_skill_multi_turn_sync(
    *,
    model: str,
    rendered_turn_prompts: List[str],
    skill_dir_abs_path: str,
    skill_id: str,
    provider_config: Optional[Dict[str, Any]] = None,
    excluded_tools: Optional[List[str]] = None,
    timeout_s: float = 600.0,
    log_dir: Optional[str] = None,
    working_directory: Optional[str] = None,
) -> AgentGenerationResult:
    runtime = get_default_runtime(log_dir=log_dir)

    async def _go() -> AgentGenerationResult:
        await runtime.start()
        return await runtime.generate_skill_multi_turn(
            model=model,
            rendered_turn_prompts=rendered_turn_prompts,
            skill_dir_abs_path=skill_dir_abs_path,
            skill_id=skill_id,
            provider_config=provider_config,
            excluded_tools=excluded_tools,
            timeout_s=timeout_s,
            working_directory=working_directory,
        )

    return _run_on_runtime_loop(_go())
