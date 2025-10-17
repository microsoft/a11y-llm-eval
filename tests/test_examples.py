import os
from pathlib import Path
import json
import pytest
import re

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
        # Only consider HTML files that include json
        for html_file in examples_dir.glob("*.html"):
            fm, _ = parse_html_with_expectations(html_file)
            if fm is None:
                # Skip HTML files without json expectations (they are invalid in the new format)
                continue
            yield (
                case_dir.name,
                html_file,
                None,
                test_js,
            )

# EXAMPLES will be computed after helper functions are defined


def _collect_assertion_names_from_testjs(test_js_path: Path):
    """Parse a test.js file and return a set of assertion names used with assert("name", ...).

    This uses a simple regex to find string literals passed as the first argument to an
    `assert(...)` call. It's intentionally permissive and assumes tests call `assert` with
    a literal string as the first argument (the common pattern in our harnesses).
    """
    content = test_js_path.read_text(encoding="utf-8")
    # Match assert(  'name'  , or assert ( `name` , or assert("name",
    pattern = re.compile(r"\bassert\s*\(\s*([\'\"`])(.+?)\1", re.DOTALL)
    names = {m.group(2) for m in pattern.finditer(content)}
    return names


# Json parser for merged HTML + json files
SCRIPT_RE = re.compile(r"<script[^>]+id=[\"']a11y-assertions[\"'][^>]*type=[\"']application/json[\"'][^>]*>(.*?)</script>", re.DOTALL | re.IGNORECASE)


def parse_html_with_expectations(path: Path):
    """Return (assertions_dict_or_None, html_text).

    This looks for a <script id="a11y-assertions" type="application/json">...json...</script>
    inside the HTML. If found, returns (parsed_json_dict, full_html_text). Otherwise (None, full_text).
    """
    text = path.read_text(encoding="utf-8")
    m = SCRIPT_RE.search(text)
    if not m:
        return None, text
    json_text = m.group(1)
    try:
        data = json.loads(json_text) or {}
    except Exception:
        return None, text
    return data, text


def _collect_assertions_for_case(case_dir: Path):
    """Return a mapping of example path -> dict(assertion name -> expected value) for examples in a case.

    This reads assertions embedded as JSON in the HTML examples using the
    <script id="a11y-assertions" type="application/json"> container. The returned
    mapping keys are Path objects referring to the example file and the values
    are dicts mapping assertion name -> normalized expectation ('pass'/'fail'/etc.).
    """
    out = {}
    examples_dir = case_dir / "examples"
    if not examples_dir.exists():
        return out

    # Include embedded JSON in HTML examples
    for html_file in examples_dir.glob("*.html"):
        fm, _ = parse_html_with_expectations(html_file)
        if not fm:
            continue
        assertion_expectations = fm.get("assertions", {}) if isinstance(fm, dict) else {}
        norm_map = {}
        for k, v in (assertion_expectations.items() if isinstance(assertion_expectations, dict) else []):
            if isinstance(v, bool):
                norm = 'pass' if v else 'fail'
            elif isinstance(v, str):
                norm = v.strip().lower()
            elif v is None:
                norm = 'none'
            else:
                norm = str(v).strip().lower()
            norm_map[k] = norm
        out[html_file] = norm_map
    return out


EXAMPLES = list(_collect_example_html())

@pytest.mark.parametrize(
    "case_name,html_path,yaml_path,test_js_path",
    EXAMPLES,
    ids=lambda p: getattr(p, "stem", p) if isinstance(p, Path) else p,
)
def test_example_html(case_name, html_path, yaml_path, test_js_path, tmp_path):
    # Load expectations from embedded JSON in the HTML
    fm, _ = parse_html_with_expectations(html_path)
    assert fm is not None, f"Example {html_path} must include embedded JSON assertions in a <script id=\"a11y-assertions\"> element"
    expectations = fm
    assertion_expectations = expectations.get("assertions", {}) if isinstance(expectations, dict) else {}
    html = html_path.read_text(encoding="utf-8")
    # Make sure screenshot dir exists
    SCREENSHOT_ROOT.mkdir(parents=True, exist_ok=True)
    screenshot_file = SCREENSHOT_ROOT / f"{case_name}__{html_path.stem}.png"

    result = node_bridge.run(html, str(test_js_path), str(screenshot_file))

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
        "embedded_assertions": expectations,
        "overall_status": status,
        "assertions": assertions,
        "assertion_results": assertion_results,
        "assertion_expectations": assertion_expectations,
        "failed_assertions": failed_assertions,
        "axe_violation_count": axe.get("violation_count") if isinstance(axe, dict) else None,
        "error": tf.get("error"),
    }
    
    assert len(failed_assertions) == 0, f"Assertion mismatches found. Details:\n{json.dumps(debug_info, indent=2)}"


def test_assertion_coverage():
    """Ensure that for each test case, the combined example YAMLs cover every assertion
    declared in the test.js file. Examples are allowed to define only a subset of assertions;
    this test enforces that collectively they reach 100% coverage of assertion names.
    """
    for case_dir in TEST_CASES_ROOT.iterdir():
        if not case_dir.is_dir():
            continue
        test_js = case_dir / "test.js"
        if not test_js.exists():
            # Skip directories that aren't test cases
            continue

        # Gather all assertion names declared in test.js
        declared = _collect_assertion_names_from_testjs(test_js)
        # Gather all assertion names mentioned in example embedded assertions for this case
        assertions_map = _collect_assertions_for_case(case_dir)

        # For missing assertions entirely (no expectation present in any example)
        names_union = set().union(*(set(d.keys()) for d in assertions_map.values())) if assertions_map else set()
        missing_entirely = declared - names_union
        if missing_entirely:
            coverage_lines = []
            for p, names in assertions_map.items():
                coverage_lines.append(f"{p}: {sorted(names.keys())}")

            msg = (
                f"Test case '{case_dir.name}' is missing expectations for {len(missing_entirely)} assertion(s):\n"
                f"  Missing: {sorted(missing_entirely)}\n"
                f"  Declared in test.js: {sorted(declared)}\n"
                f"  Example coverage:\n    " + "\n    ".join(coverage_lines)
            )
            pytest.fail(msg)

        # For each declared assertion, ensure examples collectively include both 'pass' and 'fail'
        missing_variants = {}
        for assertion in declared:
            seen = set()
            for d in assertions_map.values():
                val = d.get(assertion)
                if val:
                    seen.add(val)

            want = {"pass", "fail"}
            lacking = want - seen
            if lacking:
                missing_variants[assertion] = {
                    "seen": sorted(seen),
                    "missing": sorted(lacking),
                }

        if missing_variants:
            coverage_lines = []
            for p, names in assertions_map.items():
                coverage_lines.append(f"{p}: {sorted(names.items())}")

            msg = (
                f"Test case '{case_dir.name}' does not include both pass and fail expectations for all assertions:\n"
                f"  Details: {json.dumps(missing_variants, indent=2)}\n"
                f"  Example coverage (assertion -> expectation):\n    " + "\n    ".join(coverage_lines)
            )
            pytest.fail(msg)
