from pathlib import Path
from urllib.request import urlopen

from a11y_llm_tests import node_bridge


CHECKBOX_TEST_PATH = str((Path(__file__).resolve().parents[1] / "test_cases" / "checkbox-group" / "test.js").resolve())


def test_node_bridge_marks_broken_bootstrap_as_failed_to_render(tmp_path: Path):
    work_dir = tmp_path / "artifact"
    work_dir.mkdir()
    (work_dir / "app.js").write_text(
        "throw new Error('bootstrap failed before render');\n",
        encoding="utf-8",
    )
    html = """<!doctype html>
<html lang=\"en\">
  <head>
    <meta charset=\"utf-8\">
    <title>Broken artifact</title>
  </head>
  <body>
    <main id=\"main\"><div id=\"root\"></div></main>
    <script src=\"app.js\"></script>
  </body>
</html>
"""
    screenshot_file = str(tmp_path / "broken-artifact.png")

    result = node_bridge.run(html, CHECKBOX_TEST_PATH, screenshot_file, html_dir=str(work_dir))

    render_eval = result.get("renderEvaluation")
    assert render_eval, result
    assert render_eval.get("rendered") is False, result
    assert render_eval.get("reason") == "artifact_failed_to_render", result
    assert render_eval.get("page_errors"), result


def test_node_bridge_does_not_mark_rendered_but_inaccessible_page_as_failed_to_render(tmp_path: Path):
    html = """<!doctype html>
<html lang=\"en\">
  <body>
    <main id=\"main\">
      <form>
        <div class=\"form-field\">
          <fieldset>
            <legend>Choose topics</legend>
            <div>
              <input id=\"opt-a\" type=\"checkbox\" name=\"topics\" value=\"a\">
              <label for=\"opt-a\">Topic A</label>
            </div>
          </fieldset>
        </div>
      </form>
    </main>
  </body>
</html>
"""
    screenshot_file = str(tmp_path / "rendered-artifact.png")

    result = node_bridge.run(html, CHECKBOX_TEST_PATH, screenshot_file)

    render_eval = result.get("renderEvaluation")
    assert render_eval, result
    assert render_eval.get("rendered") is True, result
    assert render_eval.get("reason") is None, result


def test_node_bridge_serves_multi_file_artifacts_over_http(tmp_path: Path):
    work_dir = tmp_path / "artifact"
    work_dir.mkdir()
    (work_dir / "app.js").write_text(
        """
const root = document.getElementById('root');
root.innerHTML = `
  <form>
    <fieldset>
      <legend>Choose topics</legend>
      <div>
        <input id="opt-a" type="checkbox" name="topics" value="a">
        <label for="opt-a">Topic A</label>
      </div>
    </fieldset>
  </form>
`;
""".strip(),
        encoding="utf-8",
    )
    html = """<!doctype html>
<html lang="en">
  <body>
    <main id="main"><div id="root"></div></main>
    <script src="app.js"></script>
  </body>
</html>
"""

    result = node_bridge.run(html, CHECKBOX_TEST_PATH, None, html_dir=str(work_dir))

    render_eval = result.get("renderEvaluation")
    assert render_eval, result
    assert render_eval.get("rendered") is True, result
    assert render_eval.get("request_failures") == [], result
    assert result.get("testFunctionResult", {}).get("status") == "pass", result


def test_serve_directory_exposes_index_html(tmp_path: Path):
    work_dir = tmp_path / "served-run"
    work_dir.mkdir()
    (work_dir / "index.html").write_text("<html><body><h1>Report</h1></body></html>", encoding="utf-8")

    server = node_bridge.serve_directory(work_dir, port=0)
    try:
        with urlopen(server.index_url) as response:
            body = response.read().decode("utf-8")
    finally:
        server.close()

    assert "<h1>Report</h1>" in body
