
const detailedResults = require('./detailed-results');
const getName = require('./get-name');
const FIELD_WRAPPER_SELECTOR = '[class*="field"], [class*="input"], [class*="control"], [class*="item"], [class*="group"]';
let testFn = {};

// Get all text inputs
const getTextInputs = async (scope) => {
    // Native text-like inputs and textareas
    const nativeSelector = 'input[type="text"], input[type="email"], input[type="tel"], input:not([type]), textarea';
    // Custom implementations - contenteditable or role="textbox"
    const customSelector = '[contenteditable="true"], [contenteditable="plaintext-only"], [role="textbox"]';

    return scope.locator(`${nativeSelector}, ${customSelector}`);
};


// Get all form field wrappers
const getFormFields = async (scope) => {
    return await scope.locator(FIELD_WRAPPER_SELECTOR);
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

// Check that each text input has textbox role (R - WCAG 4.1.2)
testFn.testEachInputHasRole = async (scope) => {
    let results = new detailedResults();
    const formFields = await getFormFields(scope);
    const fieldCount = await formFields.count();

    if (fieldCount === 0) {
        results.addMessage("No form fields found in scope");
        return results;
    }

    let textInputFields = 0;

    // Selectors for text-input-like elements
    const textInputSelector = 'input[type="text"], input[type="email"], input[type="tel"], input:not([type]), textarea, [contenteditable="true"], [contenteditable="plaintext-only"]';
    const buttonSelector = 'button, input[type="submit"], input[type="button"]';
    const nativeInputSelector = 'input[type="text"], input[type="email"], input[type="tel"], input:not([type]), textarea';

    for (const field of await formFields.all()) {
        // Check if this field appears to be a text input field
        const hasTextInputElements = await field.locator(textInputSelector).count() > 0;
        const hasOnlyButtons = !hasTextInputElements && await field.locator(buttonSelector).count() > 0;

        if (hasOnlyButtons || !hasTextInputElements) {
            continue; // Skip button-only fields
        }

        textInputFields++;

        // Check for proper textbox role (native inputs have implicit role)
        if (await field.locator(nativeInputSelector).count() > 0) {
            results.addPass(field);
            continue;
        }

        // Check for explicit role="textbox" on custom elements
        if (await field.locator('[role="textbox"]').count() > 0) {
            results.addPass(field);
            continue;
        }

        // Otherwise: has contenteditable but no role="textbox" - failure case
        results.addFail(field);
    }

    if (textInputFields === 0) {
        results.addMessage("No text input fields found in scope");
    }

    return results;
}

// Check that helper text is programmatically associated (R - WCAG 1.3.1)
testFn.testHelperTextAssociated = async (scope) => {
    let results = new detailedResults();
    const formFields = await getFormFields(scope);
    const fieldCount = await formFields.count();

    if (fieldCount === 0) {
        results.addMessage("No form fields found in scope");
        return results;;
    }

    let fieldsWithHelperText = 0;

    // Helper text selectors - testing showed LLMs consistently use these patterns
    const helperSelector = '[class*="helper"], [class*="hint"], [class*="description"], [class*="help"], small, .form-text, p:not(:empty)';

    for (const field of await formFields.all()) {
        // Check if field has an input
        const inputLocator = field.locator('input, textarea, [role="textbox"], [contenteditable="true"]');
        if (await inputLocator.count() === 0) {
            continue;
        }

        // Check for helper text elements (excluding labels)
        const helperLocator = field.locator(helperSelector);
        const helperCount = await helperLocator.count();

        // Filter out labels from helper count
        let hasHelper = false;
        for (const helper of await helperLocator.all()) {
            const tagName = await helper.evaluate(el => el.tagName.toLowerCase());
            if (tagName !== 'label') {
                hasHelper = true;
                break;
            }
        }

        if (!hasHelper) {
            continue;
        }

        fieldsWithHelperText++;

        // Check if input has an accessible description via standard attributes
        const input = inputLocator.first();
        const describedby = await input.getAttribute('aria-describedby');
        const ariaDesc = await input.getAttribute('aria-description');
        const title = await input.getAttribute('title');
        const hasDescription = !!(describedby || ariaDesc || title);

        if (hasDescription) {
            results.addPass(field);
        } else {
            results.addFail(field);
        }
    }

    // If there's helper text, it must be associated
    // If no helper text found, pass (nothing to associate)
    if (fieldsWithHelperText === 0) {
        results.addMessage("No helper text found to associate");
        results.forcePass();
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

// Check that visible labels are programmatically associated (R - WCAG 2.4.6)
testFn.testEachInputHasLabel = async (scope) => {
    let results = new detailedResults();
    const inputs = await getTextInputs(scope);
    const count = await inputs.count();

    if (count === 0) {
        results.addMessage("No text inputs found in scope");
        return results;
    }

    for (const input of await inputs.all()) {
        const hasVisibleLabel = await input.evaluate((el) => {
            // Check for visible <label> element using axe-core's visibility check
            if (el.labels && el.labels.length > 0) {
                const label = el.labels[0];
                if (window.axe.commons.dom.isVisible(label, false, true)) {
                    return true;
                }
            }

            // Check for aria-labelledby referencing a visible element
            const labelledbyId = el.getAttribute('aria-labelledby');
            if (labelledbyId) {
                const ids = labelledbyId.split(' ');
                for (const id of ids) {
                    const labelElement = document.getElementById(id);
                    if (labelElement && window.axe.commons.dom.isVisible(labelElement, false, true)) {
                        return true;
                    }
                }
            }

            // Fallback: check if aria-label matches visible text in parent form-field
            const ariaLabel = el.getAttribute('aria-label');
            if (ariaLabel) {
                const formField = el.closest(FIELD_WRAPPER_SELECTOR);
                if (formField) {
                    const visibleText = formField.textContent || '';
                    if (visibleText.toLowerCase().includes(ariaLabel.toLowerCase().trim())) {
                        return true;
                    }
                }
            }

            return false;
        });

        if (hasVisibleLabel) {
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