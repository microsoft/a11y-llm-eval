"""Miscellaneous utility helpers."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def is_probably_complete_html(html: str) -> bool:
    """Heuristic truncation detector for standalone HTML documents.

    Goal: detect obviously cut-off files without trying to be a full HTML parser.
    """
    if not html:
        return False
    s = html.strip()
    if len(s) < 50:
        return False
    lower = s.lower()
    if "<html" not in lower or "</html>" not in lower:
        return False
    if "<body" not in lower:
        return False
    # Ensure the closing tag is near the end; truncated files often miss the tail.
    if "</html>" not in lower[-4096:]:
        return False
    return True


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Atomically write bytes to a file (temp + fsync + os.replace).

    Prevents partially written files if the process is interrupted.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd: int | None = None
    tmp_path: str | None = None
    try:
        fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.tmp.")
        with os.fdopen(fd, "wb") as f:
            fd = None
            f.write(data)
            f.flush()
            os.fsync(f.fileno())

        os.replace(tmp_path, path)

        # Best-effort durability of the directory entry.
        try:
            dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            pass
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except Exception:
                pass
        if tmp_path is not None:
            try:
                if os.path.exists(tmp_path):
                    os.unlink(tmp_path)
            except Exception:
                pass


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))


def cleanup_docker_networks(*, quiet: bool = False) -> int:
    """Tear down stale Inspect sandbox Compose projects and prune networks.

    Inspect AI creates a Docker Compose project per sandbox sample.  If cleanup
    fails (e.g. the eval errors out), containers keep running and their networks
    remain allocated.  When the predefined address pool is fully subnetted new
    sandboxes fail with ``RuntimeError: No services started``.

    This function:
    1. Lists Docker networks (``docker network ls``) and selects those whose
       names start with ``inspect-sandboxed_ag-`` (the Inspect naming
       convention, e.g. ``inspect-sandboxed_ag-XXXX_default``).
    2. Derives unique Compose project names by stripping the ``_default``
       network suffix and tears each one down with
       ``docker compose -p <project> down --remove-orphans``.
    3. Finishes with ``docker network prune`` for any remaining orphaned
       networks.

    Returns the total number of Compose projects torn down plus networks pruned
    (0 if Docker is unavailable or nothing needed cleanup).
    """
    import shutil
    import subprocess

    docker = shutil.which("docker")
    if docker is None:
        return 0

    def _run(args: list[str], timeout: int = 30) -> subprocess.CompletedProcess[str] | None:
        try:
            return subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        except (subprocess.TimeoutExpired, OSError):
            return None

    # 1. Discover stale Inspect sandbox Compose projects via their networks.
    result = _run([docker, "network", "ls", "--format", "{{.Name}}"])
    if result is None or result.returncode != 0:
        return 0

    # Inspect names networks like "inspect-sandboxed_ag-<id>_default"
    inspect_networks = [
        name.strip()
        for name in result.stdout.splitlines()
        if name.strip().startswith("inspect-sandboxed_ag-")
    ]

    # Derive unique Compose project names (network name minus the "_default" suffix).
    projects_torn_down = 0
    seen_projects: set[str] = set()
    for net_name in inspect_networks:
        # "inspect-sandboxed_ag-XXXX_default" → project "inspect-sandboxed_ag-XXXX"
        project = net_name.rsplit("_", 1)[0] if net_name.endswith("_default") else net_name
        if project in seen_projects:
            continue
        seen_projects.add(project)

        down_result = _run(
            [docker, "compose", "-p", project, "down", "--remove-orphans", "--timeout", "5"],
            timeout=30,
        )
        if down_result is not None and down_result.returncode == 0:
            projects_torn_down += 1

    # 2. Prune any remaining dangling networks.
    networks_pruned = 0
    prune_result = _run([docker, "network", "prune", "--force"])
    if prune_result is not None and prune_result.returncode == 0:
        networks_pruned = sum(
            1
            for line in prune_result.stdout.splitlines()
            if line.strip() and not line.startswith("Deleted")
        )

    return projects_torn_down + networks_pruned


def write_sha256_sidecar(target_path: Path, data: bytes) -> None:
    """Write a `<file>.sha256` sidecar for integrity checking."""
    checksum_path = target_path.with_suffix(target_path.suffix + ".sha256")
    atomic_write_bytes(checksum_path, (sha256_hex(data) + "\n").encode("utf-8"))


def read_and_validate_cached_html(html_path: Path) -> tuple[str | None, str | None]:
    """Read cached HTML and validate basic integrity.

    Returns:
        (html_text, None) on success
        (None, reason) on failure
    """
    if not html_path.exists():
        return None, "missing"

    try:
        data = html_path.read_bytes()
    except Exception:
        return None, "read-failed"

    checksum_path = html_path.with_suffix(html_path.suffix + ".sha256")
    if checksum_path.exists():
        try:
            expected = checksum_path.read_text(encoding="utf-8").strip()
            if expected and expected != sha256_hex(data):
                return None, "checksum-mismatch"
        except Exception:
            return None, "checksum-unreadable"

    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, "decode-failed"

    if not is_probably_complete_html(text):
        return None, "html-incomplete"

    return text, None
