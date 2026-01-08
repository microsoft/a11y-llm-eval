
const detailedResults = require('./detailed-results');
const getName = require('./get-name');
const { getVisualLabel, SOURCE_PLACEHOLDER } = require('./get-visual-label');
const { getAllFormFieldWrappers } = require('./get-form-field-wrapper');
const { getHelperText, SOURCE_ARIA_DESCRIBEDBY, SOURCE_TITLE } = require('./get-helper-text');

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
testFn.testEachInputHasName = async (scope) => {
    let results = new detailedResults();
    const inputs = await getTextInputs(scope);
    const count = await inputs.count();

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    for (const input of await inputs.all()){
        const name = await getName(input);
        
        if (name && name.trim().length > 0) {
            results.addPass(input);
        } else {
            results.addFail(input);
        }
    }

    return results;
}

// Check that helper text is programmatically associated (R - WCAG 1.3.1)
testFn.testHelperTextAssociated = async (scope) => {
    let results = new detailedResults();
    const inputs = await getTextInputs(scope);
    const count = await inputs.count();

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    for (const input of await inputs.all()) {
        const helperText = await getHelperText(input);
        // Exclude placeholder-only labels since they are not persistant visible labels
        if (helperText.text.trim().length == 0) {
            continue; // no helper text to check
        }
        
        if (helperText.source == SOURCE_ARIA_DESCRIBEDBY || helperText.source == SOURCE_TITLE) {
            results.addPass(input);
        } else {
            results.addFail(input);
        }
    }

    return results;
}

// Check that text inputs are keyboard focusable (R - WCAG 2.1.1)
testFn.testEachInputFocusable = async (scope) => {
    let results = new detailedResults();
    const inputs = await getTextInputs(scope);
    const count = await inputs.count();

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    for (const input of await inputs.all()) {
        // Skip hidden inputs
        if (!await input.isVisible()) {
            continue;
        }

        // Check tabindex - elements with tabindex < 0 are not keyboard navigable
        // (they can receive programmatic focus but not Tab navigation)
        const tabindex = await input.getAttribute('tabindex');
        const isKeyboardNavigable = tabindex === null || parseInt(tabindex, 10) >= 0;

        if (isKeyboardNavigable) {
            results.addPass(input);
        } else {
            results.addFail(input);
        }
    }

    return results;
}

// Check that persistant visible labels are defined (R - WCAG 2.4.6)
testFn.testEachInputHasPersistantVisualLabel = async (scope) => {
    let results = new detailedResults();
    const inputs = await getTextInputs(scope);
    const count = await inputs.count();

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    for (const input of await inputs.all()) {
        const visualLabel = await getVisualLabel(input);
        // Exclude placeholder-only labels since they are not persistant visible labels
        if (visualLabel && visualLabel.text.trim().length > 0 && visualLabel.source !== SOURCE_PLACEHOLDER) {
            results.addPass(input);
        } else {
            results.addFail(input);
        }
    }

    return results;
}

testFn.testRequiredFieldsIndicated = async (scope) => {
    let results = new detailedResults();
    const inputs = await getTextInputs(scope);
    const count = await inputs.count();

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    // Check if any inputs appear to be required (by visual indicators or context)
    // and verify they have proper programmatic indication
    let visuallyRequiredCount = 0;

    for (const input of await inputs.all()) {
        // Check programmatic indication using Playwright getAttribute
        const hasRequiredAttr = await input.getAttribute('required') !== null;
        const hasAriaRequired = await input.getAttribute('aria-required') === 'true';
        const isProgrammaticallyRequired = hasRequiredAttr || hasAriaRequired;

        // Check for visual required indicators in parent form-field
        const formField = input.locator('xpath=ancestor::*[contains(@class, "form-field")]').first();
        let hasVisualIndicator = false;

        if (await formField.count() > 0) {
            const fieldText = await formField.textContent() || '';
            hasVisualIndicator = fieldText.includes('*') ||
                                fieldText.toLowerCase().includes('required');
        }

        if (hasVisualIndicator) {
            visuallyRequiredCount++;
            if (isProgrammaticallyRequired) {
                results.addPass(input);
            } else {
                results.addFail(input);
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

module.exports = testFn;