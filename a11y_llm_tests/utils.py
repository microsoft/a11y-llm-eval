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


def check_docker_network_pool(*, max_networks: int = 30) -> None:
    """Fail early if Docker's bridge-network address pool is nearly exhausted.

    Docker's default address pool supports roughly 30 bridge networks.
    Each Inspect sandbox allocates one.  If most slots are already taken,
    new sandboxes will fail with ``RuntimeError: No services started``
    partway through a run, wasting time and API credits.

    Only *bridge* networks are counted — host, none, overlay, and other
    driver types don't consume slots from the default address pool, so
    machines with many unrelated networks won't trigger false positives.

    This function raises ``RuntimeError`` when the bridge-network count
    is at or above *max_networks*, giving operators a clear message to
    clean up before proceeding.  It does **not** remove any networks or
    containers itself.

    Raises:
        RuntimeError: When the bridge-network count meets or exceeds *max_networks*.
    """
    import shutil
    import subprocess

    docker = shutil.which("docker")
    if docker is None:
        return

    try:
        result = subprocess.run(
            [docker, "network", "ls", "--filter", "driver=bridge",
             "--format", "{{.Name}}"],
            capture_output=True, text=True, timeout=15,
        )
    except (subprocess.TimeoutExpired, OSError):
        return

    if result.returncode != 0:
        return

    network_count = sum(1 for line in result.stdout.splitlines() if line.strip())
    if network_count >= max_networks:
        raise RuntimeError(
            f"Docker has {network_count} bridge networks (limit ~{max_networks}). "
            f"Agent sandboxes are likely to fail with address-pool exhaustion. "
            f"Free up networks before running agent generation:\n"
            f"  docker network prune --force\n"
            f"  # or tear down stale Inspect sandboxes:\n"
            f"  docker ps -a --filter 'name=inspect-sandboxed_ag-' -q | xargs -r docker rm -f\n"
            f"  docker network prune --force"
        )


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
