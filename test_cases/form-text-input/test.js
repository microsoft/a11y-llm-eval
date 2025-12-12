/**
 * Form Text Input accessibility test assertions
 * Tests WCAG 4.1.2, 2.1.1, 2.4.7, 1.3.1, 3.3.2
 */

/**
 * Get all text input elements, including native inputs and custom implementations.
 * This finds elements that appear to be text inputs for testing purposes,
 * regardless of whether they have proper ARIA roles.
 */
const getTextInputs = async (page) => {
    // Native text-like inputs and textareas
    const nativeSelector = 'input[type="text"], input[type="email"], input[type="tel"], input:not([type]), textarea';
    // Custom implementations - contenteditable or role="textbox"
    const customSelector = '[contenteditable="true"], [contenteditable="plaintext-only"], [role="textbox"]';

    return page.locator(`${nativeSelector}, ${customSelector}`);
};

/**
 * Get all form field wrappers
 */
const getFormFields = async (page) => {
    return await page.locator('.form-field');
};

module.exports.run = async ({ page, assert, utils }) => {

    // Assertion 1: Each text input has an accessible name (R - WCAG 4.1.2, 1.3.1, 3.3.2)
    await assert("Each text input has an accessible name", async () => {
        const inputs = await getTextInputs(page);
        const count = await inputs.count();

        if (count === 0) {
            return { pass: false, message: "No text inputs found on the page" };
        }

        let passCount = 0;
        for (let i = 0; i < count; i++) {
            const input = inputs.nth(i);

            const hasAccessibleName = await input.evaluate((el) => {
                const accName = window.axe.commons.text.accessibleText(el);
                if (!accName || accName.trim().length === 0) {
                    return false;
                }

                // Exclude cases where accessible name comes only from placeholder (WCAG 3.3.2)
                const placeholder = el.getAttribute('placeholder');
                if (placeholder && accName.trim() === placeholder.trim()) {
                    return false;
                }

                return true;
            });

            if (hasAccessibleName) {
                passCount++;
            }
        }

        return passCount === count;
    });

    // Assertion 2: Each text input has textbox role (R - WCAG 4.1.2)
    // Check that form fields intended for text input contain proper textbox elements
    await assert("Each text input has textbox role", async () => {
        const formFields = await getFormFields(page);
        const fieldCount = await formFields.count();

        if (fieldCount === 0) {
            return { pass: false, message: "No form fields found" };
        }

        let textInputFields = 0;
        let fieldsWithTextbox = 0;

        // Selectors for text-input-like elements
        const textInputSelector = 'input[type="text"], input[type="email"], input[type="tel"], input:not([type]), textarea, [contenteditable="true"], [contenteditable="plaintext-only"]';
        const buttonSelector = 'button, input[type="submit"], input[type="button"]';
        const nativeInputSelector = 'input[type="text"], input[type="email"], input[type="tel"], input:not([type]), textarea';

        for (let i = 0; i < fieldCount; i++) {
            const field = formFields.nth(i);

            // Check if this field appears to be a text input field
            const hasTextInputElements = await field.locator(textInputSelector).count() > 0;
            const hasOnlyButtons = !hasTextInputElements && await field.locator(buttonSelector).count() > 0;

            if (hasOnlyButtons || !hasTextInputElements) {
                continue; // Skip button-only fields
            }

            textInputFields++;

            // Check for proper textbox role (native inputs have implicit role)
            if (await field.locator(nativeInputSelector).count() > 0) {
                fieldsWithTextbox++;
                continue;
            }

            // Check for explicit role="textbox" on custom elements
            if (await field.locator('[role="textbox"]').count() > 0) {
                fieldsWithTextbox++;
            }
            // Otherwise: has contenteditable but no role="textbox" - failure case
        }

        if (textInputFields === 0) {
            return { pass: false, message: "No text input fields found" };
        }

        return fieldsWithTextbox === textInputFields;
    });

    // Assertion 3: Helper text is programmatically associated (R - WCAG 1.3.1)
    await assert("Helper text is programmatically associated", async () => {
        const formFields = await getFormFields(page);
        const fieldCount = await formFields.count();

        if (fieldCount === 0) {
            return { pass: false, message: "No form fields found" };
        }

        let fieldsWithHelperText = 0;
        let fieldsWithAssociatedHelper = 0;

        // Helper text selectors - testing showed LLMs consistently use these patterns
        const helperSelector = '[class*="helper"], [class*="hint"], [class*="description"], [class*="help"], small, .form-text, p:not(:empty)';

        for (let i = 0; i < fieldCount; i++) {
            const field = formFields.nth(i);

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
            for (let j = 0; j < helperCount; j++) {
                const helper = helperLocator.nth(j);
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
                fieldsWithAssociatedHelper++;
            }
        }

        // If there's helper text, it must be associated
        // If no helper text found, pass (nothing to associate)
        if (fieldsWithHelperText === 0) {
            return { pass: true, message: "No helper text found to associate" };
        }

        return fieldsWithAssociatedHelper === fieldsWithHelperText;
    });

    // Assertion 4: Text inputs are keyboard focusable (R - WCAG 2.1.1)
    await assert("Text inputs are keyboard focusable", async () => {
        const inputs = await getTextInputs(page);
        const count = await inputs.count();

        if (count === 0) {
            return { pass: false, message: "No text inputs found on the page" };
        }

        let focusableCount = 0;

        for (let i = 0; i < count; i++) {
            const input = inputs.nth(i);

            // Skip hidden inputs
            if (!await input.isVisible()) {
                continue;
            }

            // Check tabindex - elements with tabindex < 0 are not keyboard navigable
            // (they can receive programmatic focus but not Tab navigation)
            const tabindex = await input.getAttribute('tabindex');
            const isKeyboardNavigable = tabindex === null || parseInt(tabindex, 10) >= 0;

            if (isKeyboardNavigable) {
                focusableCount++;
            }
        }

        return focusableCount === count;
    });

    // Assertion 5: Visible labels are programmatically associated (R - WCAG 2.4.6)
    // Note: This tests that visible label text is accessible to screen readers via:
    // 1. Programmatic association (label[for], aria-labelledby) - preferred
    // 2. aria-label that matches visible text in the form field - acceptable fallback
    await assert("Visible label text is accessible", async () => {
        const inputs = await getTextInputs(page);
        const count = await inputs.count();

        if (count === 0) {
            return { pass: false, message: "No text inputs found on the page" };
        }

        let visibleLabelCount = 0;

        for (let i = 0; i < count; i++) {
            const input = inputs.nth(i);

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
                    const formField = el.closest('.form-field');
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
                visibleLabelCount++;
            }
        }

        return visibleLabelCount === count;
    });

    // Assertion 6: Required fields are programmatically indicated (BP - WCAG 3.3.2)
    await assert("Required fields are programmatically indicated", async () => {
        const inputs = await getTextInputs(page);
        const count = await inputs.count();

        if (count === 0) {
            return { pass: false, message: "No text inputs found on the page" };
        }

        // Check if any inputs appear to be required (by visual indicators or context)
        // and verify they have proper programmatic indication
        let visuallyRequiredCount = 0;
        let programmaticallyIndicatedCount = 0;

        for (let i = 0; i < count; i++) {
            const input = inputs.nth(i);

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
                    programmaticallyIndicatedCount++;
                }
            }
        }

        // If fields appear required visually, they should be programmatically indicated
        // If no visually required fields, we pass (nothing to check)
        if (visuallyRequiredCount === 0) {
            return { pass: true, message: "No visually required fields found" };
        }

        return programmaticallyIndicatedCount === visuallyRequiredCount;
    }, { type: 'BP' });

    return {}; // assertions collected via injected assert
};
