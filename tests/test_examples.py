import os
from pathlib import Path
import json
import pytest
import yaml
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
        # Only consider HTML files that include front-matter (merged format)
        for html_file in examples_dir.glob("*.html"):
            fm, _ = parse_html_with_front_matter(html_file)
            if fm is None:
                # Skip HTML files without front-matter (they are invalid in the new format)
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


# Front-matter parser for merged HTML + YAML files
FRONT_RE = re.compile(r"\A---\s*\n(.*?\n)---\s*\n", re.DOTALL)


def parse_html_with_front_matter(path: Path):
    """Return (front_matter_dict_or_None, html_text).

    If the file begins with a YAML front-matter block (--- ... ---), parse it and
    return (data, rest_of_file). Otherwise return (None, full_file_text).
    """
    text = path.read_text(encoding="utf-8")
    m = FRONT_RE.match(text)
    if not m:
        return None, text
    yaml_block = m.group(1)
    try:
        data = yaml.safe_load(yaml_block) or {}
    except Exception:
        # If front-matter is malformed, treat as no front-matter so existing
        # behavior using separate YAML files can still apply.
        return None, text
    html = text[m.end():]
    return data, html


def _collect_yaml_assertions_for_case(case_dir: Path):
    """Return a mapping of yaml path -> dict(assertion name -> expected value) for all example yamls in a case.

    The expected value is normalized to a lowercase string: booleans map to 'pass'/'fail', strings are lowercased.
    """
    out = {}
    examples_dir = case_dir / "examples"
    if not examples_dir.exists():
        return out
    for yaml_file in examples_dir.glob("*.yaml"):
        try:
            with open(yaml_file, 'r', encoding='utf-8') as f:
                expectations = yaml.safe_load(f) or {}
        except Exception:
            expectations = {}
        assertion_expectations = expectations.get("assertions", {}) if isinstance(expectations, dict) else {}
        norm_map = {}
        for k, v in (assertion_expectations.items() if isinstance(assertion_expectations, dict) else []):
            # normalize expectation values
            if isinstance(v, bool):
                norm = 'pass' if v else 'fail'
            elif isinstance(v, str):
                norm = v.strip().lower()
            elif v is None:
                norm = 'none'
            else:
                norm = str(v).strip().lower()
            norm_map[k] = norm
        out[yaml_file] = norm_map
    # Also include front-matter in HTML files (for merged examples)
    for html_file in examples_dir.glob("*.html"):
        # Skip if we already have a separate YAML for this example
        if html_file.with_suffix('.yaml') in out:
            continue
        fm, _ = parse_html_with_front_matter(html_file)
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
    # Load expectations from front-matter in the HTML (merged format only)
    fm, _ = parse_html_with_front_matter(html_path)
    assert fm is not None, f"Example {html_path} must include YAML front-matter with expectations"
    expectations = fm
    assertion_expectations = expectations.get("assertions", {}) if isinstance(expectations, dict) else {}
    
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
        # Gather all assertion names mentioned in example front-matter for this case
        yaml_map = _collect_yaml_assertions_for_case(case_dir)

        # For missing assertions entirely (no expectation present in any example)
        yaml_names_union = set().union(*(set(d.keys()) for d in yaml_map.values())) if yaml_map else set()
        missing_entirely = declared - yaml_names_union
        if missing_entirely:
            coverage_lines = []
            for p, names in yaml_map.items():
                coverage_lines.append(f"{p}: {sorted(names.keys())}")

            msg = (
                f"Test case '{case_dir.name}' is missing expectations for {len(missing_entirely)} assertion(s):\n"
                f"  Missing: {sorted(missing_entirely)}\n"
                f"  Declared in test.js: {sorted(declared)}\n"
                f"  YAML coverage:\n    " + "\n    ".join(coverage_lines)
            )
            pytest.fail(msg)

        # For each declared assertion, ensure examples collectively include both 'pass' and 'fail'
        missing_variants = {}
        for assertion in declared:
            seen = set()
            for d in yaml_map.values():
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
            for p, names in yaml_map.items():
                coverage_lines.append(f"{p}: {sorted(names.items())}")

            msg = (
                f"Test case '{case_dir.name}' does not include both pass and fail expectations for all assertions:\n"
                f"  Details: {json.dumps(missing_variants, indent=2)}\n"
                f"  YAML coverage (assertion -> expectation):\n    " + "\n    ".join(coverage_lines)
            )
            pytest.fail(msg)
