
const detailedResults = require('./detailed-results');
const getName = require('./get-name');
const { getVisualLabel, SOURCE_PLACEHOLDER } = require('./get-visual-label');
const { getAllFormFieldWrappers } = require('./get-form-field-wrapper');
const { getHelperText, SOURCE_ARIA_DESCRIBEDBY, SOURCE_TITLE } = require('./get-helper-text');
const { discover } = require('./discovery');

let testFn = {};

// Get all text inputs
const getTextInputs = async (scope) => {
    return scope.getByRole('textbox');
};


// Get all form field wrappers
const getFormFields = async (scope) => {
    return await getAllFormFieldWrappers(scope);
};

// Check that each text input has an accessible name (R - WCAG 4.1.2)
testFn.testEachInputHasName = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    for (const item of d.inputs) {
        const name = item.name;
        if (name && name.trim().length > 0) {
            results.addPass(item.locator);
        } else {
            results.addFail(item.locator);
        }
    }

    return results;
}

// Check that helper text is programmatically associated (R - WCAG 1.3.1)
testFn.testHelperTextAssociated = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    for (const item of d.inputs) {
        const helperText = item.helperText;
        if (!helperText || helperText.text.trim().length === 0) {
            continue; // no helper text to check
        }
        if (helperText.source == SOURCE_ARIA_DESCRIBEDBY || helperText.source == SOURCE_TITLE) {
            results.addPass(item.locator);
        } else {
            results.addFail(item.locator);
        }
    }

    return results;
}

// Check that text inputs are keyboard focusable (R - WCAG 2.1.1)
testFn.testEachInputFocusable = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    for (const item of d.inputs) {
        if (!item.visible) {
            continue; // skip hidden inputs
        }
        const tabindex = item.tabIndex;
        const isKeyboardNavigable = tabindex === null || parseInt(tabindex, 10) >= 0;
        if (isKeyboardNavigable) {
            results.addPass(item.locator);
        } else {
            results.addFail(item.locator);
        }
    }

    return results;
}

// Check that persistant visible labels are defined (R - WCAG 2.4.6)
// This does not consider placeholder-only labels as persistant visible labels, and does not check for programmatic association
testFn.testEachInputHasPersistantVisualLabel = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    for (const item of d.inputs) {
        const visualLabel = item.visualLabel;
        if (visualLabel && visualLabel.text.trim().length > 0 && visualLabel.source !== SOURCE_PLACEHOLDER) {
            results.addPass(item.locator);
        } else {
            results.addFail(item.locator);
        }
    }

    return results;
}

testFn.testRequiredFieldsIndicated = async (scope, discoveryCache) => {
    let results = new detailedResults();
    const d = discoveryCache || await discover(scope);
    const count = d.inputs.length;

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    // Check if any inputs appear to be required (by visual indicators in label/help)
    // and verify they have proper programmatic indication
    let visuallyRequiredCount = 0;

    // Helper to detect an asterisk at start or end of a label
    const hasAsteriskRequiredIndicator = (labelObj) => {
        if (!labelObj || !labelObj.text) return false;
        const text = labelObj.text.trim();
        // Allow optional punctuation/colon around the asterisk
        return text.startsWith('*') || text.endsWith('*');
    };

    // Helper to detect textual indicators for required while avoiding content descriptions
    const hasTextualRequiredIndicator = (rawText) => {
        if (!rawText) return false;
        const t = String(rawText).toLowerCase().trim();

        // Strong signals first
        if (/\(\s*required\s*\)/.test(t)) return true; // '(required)'
        if (/\bmandatory\b/.test(t)) return true;        // 'mandatory'

        // Phrases that indicate the field itself is required
        if (/\bis required\b/.test(t)) return true;      // 'is required'
        if (/\brequired field\b/.test(t)) return true;   // 'required field'

        // Trailing 'required' at the end of the string (optionally with punctuation)
        if (/(^|\s)required[\s\.!?)]*$/.test(t)) return true;

        // Avoid cases like 'required length', 'required format', etc., where 'required'
        // describes the content rather than the field requirement.
        if (/\brequired\s+(length|format|characters?|fields?|value|values|minimum|password|pattern|items?)\b/.test(t)) {
            return false;
        }

        return false;
    };

    for (const item of d.inputs) {
        const isProgrammaticallyRequired = item.programmaticallyRequired;
        const label = item.visualLabel;
        const helpText = item.helperText;

        // Determine if this field looks required based on the label/help text
        const labelIndicatesRequired = hasAsteriskRequiredIndicator(label) || hasTextualRequiredIndicator(label?.text);
        const helpTextIndicatesRequired = hasTextualRequiredIndicator(helpText?.text);
        const hasVisualIndicator = labelIndicatesRequired || helpTextIndicatesRequired;

        if (hasVisualIndicator) {
            visuallyRequiredCount++;
            if (isProgrammaticallyRequired) {
                results.addPass(item.locator);
            } else {
                results.addFail(item.locator);
            }
        }
    }

    // If fields appear required visually, they should be programmatically indicated
    // If no visually required fields, we pass (nothing to check)
    if (visuallyRequiredCount === 0) {
        results.addMessage("No visually required fields found");
        results.forcePass();
    }

    return results;
}

// Expose discovery so callers can prime and pass a cache
testFn.discover = discover;

module.exports = testFn;