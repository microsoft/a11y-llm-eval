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
        ├── example1.html  # HTML example file
        ├── example1.yaml  # YAML file defining assertion expectations for example1.html
        ├── example2.html  # Another HTML example file
        └── example2.yaml  # YAML file defining assertion expectations for example2.html
```

## YAML Expectation Files

Each HTML example file should have a corresponding YAML file with the same basename that defines which assertions should pass or fail for that specific example.

### Format

```yaml
assertions:
  "Assertion Name 1": pass  # or fail
  "Assertion Name 2": fail
  "Assertion Name 3": pass
```

### Example

For a file `shopping-cart.html`, create `shopping-cart.yaml`:

```yaml
assertions:
  "Has an h1": pass
  "Has single h1": pass
  "Has at least one h2": fail
  "Has a single banner": pass
  "Has a single footer": pass
```

## Benefits

1. **Performance**: Each HTML file is only processed once by the node runner, regardless of how many assertions it contains.
2. **Flexibility**: You can have multiple example files for each test case, each with different assertion expectations.
3. **Granular Testing**: Individual assertions can be tested separately, making it easier to identify specific failures.
4. **Clear Expectations**: The YAML files make it explicit which assertions should pass or fail for each example.
