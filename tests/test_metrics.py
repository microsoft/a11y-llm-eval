from a11y_llm_tests.metrics import compute_pass_at_k, format_pass_at_k


def test_pass_at_k_basic_cases():
    # All fail
    assert compute_pass_at_k(0, 5, [1, 2, 5]) == {1: 0.0, 2: 0.0, 5: 0.0}
    # All pass
    assert compute_pass_at_k(5, 5, [1, 2, 5]) == {1: 1.0, 2: 1.0, 5: 1.0}
    # Example: n=5, c=1
    r = compute_pass_at_k(1, 5, [1, 2])
    # pass@1 = c/n = 0.2
    assert abs(r[1] - 0.2) < 1e-9
    # pass@2 = 1 - ( (4C2)/(5C2) ) = 1 - (6/10) = 0.4
    assert abs(r[2] - 0.4) < 1e-9


def test_pass_at_k_edge_values():
    # k larger than n
    r = compute_pass_at_k(1, 3, [5])
    # k treated as n => probability that at least one passes = 1 when c>0
    assert r[5] == 1.0
    # zero samples
    r0 = compute_pass_at_k(0, 0, [1, 5])
    assert r0 == {1: 0.0, 5: 0.0}


def test_format_pass_at_k():
    formatted = format_pass_at_k({5: 1.0, 1: 0.2})
    # Keys become strings and sorted
    assert list(formatted.keys()) == ["1", "5"]
    assert formatted["1"] == 0.2
    assert formatted["5"] == 1.0
