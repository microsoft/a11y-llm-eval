"""a11y_llm_tests

Toolkit to evaluate how well various LLMs generate accessible HTML.

Primary entrypoints:
 - cli.py (Typer CLI)
 - generator.py (LLM generation + caching)
 - node_bridge.py (Puppeteer + axe-core invocation)
 - report.py (HTML report rendering)
"""

__all__ = [
    "generator",
    "node_bridge",
    "report",
]
