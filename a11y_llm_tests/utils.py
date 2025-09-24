"""Miscellaneous utility helpers (placeholder)."""

def ensure_single_html(doc: str) -> str:
    """Return only the first <html>...</html> segment if multiple exist."""
    lower = doc.lower()
    if "<html" in lower and "</html>" in lower:
        start = lower.index("<html")
        end = lower.index("</html>") + len("</html>")
        return doc[start:end]
    return doc
