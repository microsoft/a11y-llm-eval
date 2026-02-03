"""Miscellaneous utility helpers."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path


def ensure_single_html(doc: str) -> str:
    """Return only the first <html>...</html> segment if multiple exist."""
    lower = doc.lower()
    if "<html" in lower and "</html>" in lower:
        start = lower.index("<html")
        end = lower.index("</html>") + len("</html>")
        return doc[start:end]
    return doc


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
