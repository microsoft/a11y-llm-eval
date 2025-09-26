import os
from pathlib import Path
import json
import pytest
import yaml

from a11y_llm_tests import node_bridge

TEST_CASES_ROOT = Path("test_cases")
SCREENSHOT_ROOT = Path("runs") / "pytest_screenshots"

def _collect_example_html():
    """Yield tuples: (test_case_name, html_path, yaml_path, test_js_path)."""
    for case_dir in TEST_CASES_ROOT.iterdir():
        if not case_dir.is_dir():
            continue
        test_js = case_dir / "test.js"
        if not test_js.exists():
            continue
        examples_dir = case_dir / "examples"
        if not examples_dir.exists():
            continue
        for html_file in examples_dir.glob("*.html"):
            yaml_file = html_file.with_suffix(".yaml")
            if yaml_file.exists():
                yield (
                    case_dir.name,
                    html_file,
                    yaml_file,
                    test_js,
                )

EXAMPLES = list(_collect_example_html())

@pytest.mark.parametrize(
    "case_name,html_path,yaml_path,test_js_path",
    EXAMPLES,
    ids=lambda p: getattr(p, "stem", p) if isinstance(p, Path) else p,
)
def test_example_html(case_name, html_path, yaml_path, test_js_path, tmp_path):
    # Load expectations from YAML file
    with open(yaml_path, 'r', encoding='utf-8') as f:
        expectations = yaml.safe_load(f)
    
    assertion_expectations = expectations.get("assertions", {})
    
    html = html_path.read_text(encoding="utf-8")
    # Make sure screenshot dir exists
    SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    screenshot_file = SCREENSHOT_ROOT / f"{case_name}__{html_path.stem}.png"

    result = node_bridge.run_in_puppeteer(html, str(test_js_path), str(screenshot_file))

    if "error" in result and result["error"]:
        print(f"Error running test case {case_name} with HTML {html_path}: {result['error']}")

    tf = result.get("testFunctionResult", {})
    status = tf.get("status")
    assertions = tf.get("assertions", [])  # Assertions may now include type ('R' or 'BP')
    axe = result.get("axeResult") or result.get("axe_result") or result.get("axe")

    # Build a map of assertion name to result
    assertion_results = {}
    for assertion in assertions:
        assertion_name = assertion.get("name")
        assertion_status = assertion.get("status")
        if assertion_name:
            assertion_results[assertion_name] = assertion_status

    # Test each assertion individually
    failed_assertions = []
    for assertion_name, expected_result in assertion_expectations.items():
        actual_result = assertion_results.get(assertion_name)
        if actual_result != expected_result:
            failed_assertions.append({
                "assertion": assertion_name,
                "expected": expected_result,
                "actual": actual_result
            })

    debug_info = {
        "case": case_name,
        "html_example": str(html_path),
        "yaml_expectations": str(yaml_path),
        "overall_status": status,
        "assertions": assertions,
        "assertion_results": assertion_results,
        "assertion_expectations": assertion_expectations,
        "failed_assertions": failed_assertions,
        "axe_violation_count": axe.get("violation_count") if isinstance(axe, dict) else None,
        "error": tf.get("error"),
    }
    
    assert len(failed_assertions) == 0, f"Assertion mismatches found. Details:\n{json.dumps(debug_info, indent=2)}"
