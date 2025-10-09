# Example Test Structure Documentation

This document explains the new structure for test cases and their examples.

## Directory Structure

Each test case should have the following structure:

```
test_cases/
└── <test-case-name>/
    ├── prompt.md          # Prompt to generate code for the test case
    ├── test.js            # JavaScript test assertions
    └── examples/          # Directory containing example HTML files and expectations
        ├── example1.html  # HTML example file with embedded json expectations for assertions
        ├── example2.html  # Another HTML example file with embedded json expectations for assertions
```

## Embedded JSON expectations for assertions

Each HTML example file should have a script tag in the `<head>` that defines which assertions should pass or fail for that specific example.

### Format

```html
<script id="a11y-assertions" type="application/json">{
    "assertions": {
        "assertion name": "value",
    }
}</script>
```

### Example

```html
<script id="a11y-assertions" type="application/json">{
    "assertions": {
        "All examples have a valid semantics": "pass",
        "Collapsed content is hidden from assistive technology": "pass"
    }
}</script>
```

## Benefits

1. **Performance**: Each HTML file is only processed once by the node runner, regardless of how many assertions it contains.
2. **Flexibility**: You can have multiple example files for each test case, each with different assertion expectations.
3. **Granular Testing**: Individual assertions can be tested separately, making it easier to identify specific failures.
4. **Clear Expectations**: The JSON make it explicit which assertions should pass or fail for each example.
